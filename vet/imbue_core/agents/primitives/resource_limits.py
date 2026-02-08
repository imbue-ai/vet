import asyncio
import datetime
import os
from asyncio import CancelledError
from asyncio import Task
from asyncio import TaskGroup
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import Optional
from uuid import uuid4

import attr
from loguru import logger

from vet.imbue_core.agents.primitives.errors import DollarLimitExceeded
from vet.imbue_core.agents.primitives.errors import MaximumSpendExceeded
from vet.imbue_core.async_monkey_patches import safe_cancel
from vet.imbue_core.itertools import first
from vet.imbue_core.serialization_types import Serializable
from vet.imbue_core.time_utils import get_current_time

# TODO: someday in the future we can be smarter about this...
_AUTH_PAYMENT_TIMEOUT_SECONDS = 60 * 60 * 24
_ONE_HOUR_IN_SECONDS = 60 * 60


class InvalidResourceLimitsError(Exception):
    pass


class AuthorizationInvalidated(Exception):
    pass


@attr.s(auto_attribs=True, frozen=True)
class PaymentAuthorization:
    dollars: float
    authorization_id: str
    authorized_at: datetime.datetime


@attr.s(auto_attribs=True, frozen=True)
class ResourceLimitState(Serializable):
    hard_cap_dollars: float
    hard_cap_seconds: float
    warn_cap_dollars: float
    warn_cap_seconds: float
    dollars_per_hour: float | None

    @classmethod
    def build_for_increase(
        cls,
        hard_cap_dollars: float = 0.001,
        hard_cap_seconds: float = 0.001,
        warn_cap_dollars: float = 0.001,
        warn_cap_seconds: float = 0.001,
        dollars_per_hour: float | None = None,
    ) -> "ResourceLimitState":
        return cls(
            hard_cap_dollars=hard_cap_dollars,
            hard_cap_seconds=hard_cap_seconds,
            warn_cap_dollars=warn_cap_dollars,
            warn_cap_seconds=warn_cap_seconds,
            dollars_per_hour=dollars_per_hour,
        )


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value)


@attr.s(auto_attribs=True)
class ResourceLimits:
    hard_cap_dollars: float
    hard_cap_seconds: float
    warn_cap_dollars: float
    warn_cap_seconds: float
    # note that setting this effectively caps the size of any given authorization request to this quantity as well
    # (since it is impossible to spend less than $X per hour if you are spending $X+1 in total)
    # in such a case, MaximumSpendExceeded will be raised
    dollars_per_hour: float | None = None
    parent_limits: Optional["ResourceLimits"] = None
    dollars_spent: float = 0.0
    save_spend_callback: Callable[[float], Coroutine[Any, Any, None]] | None = None
    open_authorizations: dict[str, PaymentAuthorization] = attr.ib(factory=dict)
    recent_spend_events: list[PaymentAuthorization] = attr.ib(factory=list)
    # ensure that only a single spend is being authorized at once
    spend_lock: asyncio.Lock = attr.ib(factory=asyncio.Lock)
    # prevent us from mutating our state from multiple coroutines at once
    state_lock: asyncio.Lock = attr.ib(factory=asyncio.Lock)
    # triggered when the limits are updated
    limits_updated_event: asyncio.Event = attr.ib(factory=asyncio.Event)
    # triggered when a settlement happens
    next_settlement_event: asyncio.Event = attr.ib(factory=asyncio.Event)

    @classmethod
    def build(
        cls,
        *,
        max_dollars: float | None = None,
        max_seconds: float | None = None,
        warn_fraction: float | None = None,
        dollars_per_hour: float | None = None,
    ) -> "ResourceLimits":
        if max_dollars is None and "DEFAULT_MAX_HAMMER_DOLLARS" in os.environ:
            max_dollars = _float_or_none(os.getenv("DEFAULT_MAX_HAMMER_DOLLARS"))
        if max_dollars is None:
            max_dollars = 0.0
        assert max_dollars >= 0, "max_dollars must be non-negative"
        if max_seconds is None and "DEFAULT_MAX_HAMMER_SECONDS" in os.environ:
            max_seconds = _float_or_none(os.getenv("DEFAULT_MAX_HAMMER_SECONDS"))
        if max_seconds is None:
            max_seconds = float("inf")
        assert max_seconds >= 0, "max_seconds must be non-negative"
        if warn_fraction is None:
            # TODO: is it DEFAULT_WARN_FRACTION or DEFAULT_HAMMER_WARN_FRACTION?
            if "DEFAULT_WARN_FRACTION" in os.environ:
                warn_fraction = _float_or_none(os.getenv("DEFAULT_HAMMER_WARN_FRACTION"))
                assert warn_fraction is not None
            else:
                warn_fraction = 0.25
        if dollars_per_hour is None and "DEFAULT_DOLLARS_PER_HOUR" in os.environ:
            dollars_per_hour = _float_or_none(os.getenv("DEFAULT_DOLLARS_PER_HOUR"))
        result = cls(
            hard_cap_dollars=max_dollars,
            hard_cap_seconds=max_seconds,
            warn_cap_dollars=max_dollars * warn_fraction,
            warn_cap_seconds=max_seconds * warn_fraction,
            dollars_per_hour=dollars_per_hour,
        )
        # check that we're not currently in a hammer, otherwise should be calling create_restricted_limits instead
        try:
            if get_global_resource_limits() is not None:
                # If you encounter this, it probably means you're trying to mix hammer and non-hammer resource limiting.
                # For simplicity and correctness, try to avoid that.
                raise InvalidResourceLimitsError(
                    "Should not create a new ResourceLimits while global limits are in place. Instead, call create_restricted_limits"
                )
        except RuntimeError:
            pass
        return result

    def create_restricted_limits(
        self,
        *,
        max_dollars: float | None = None,
        max_seconds: float | None = None,
        warn_fraction: float | None = None,
        hard_cap_dollars: float | None = None,
        hard_cap_seconds: float | None = None,
        warn_cap_dollars: float | None = None,
        warn_cap_seconds: float | None = None,
        dollars_per_hour: float | None = None,
    ) -> "ResourceLimits":
        if max_dollars is not None:
            assert hard_cap_dollars is None, "Cannot specify both max_dollars and hard_cap_dollars"
            hard_cap_dollars = max_dollars
            if warn_fraction is not None:
                assert warn_cap_dollars is None, "Cannot specify both warn_fraction and warn_cap_dollars"
                warn_cap_dollars = max_dollars * warn_fraction

        if max_seconds is not None:
            assert hard_cap_seconds is None, "Cannot specify both max_seconds and hard_cap_seconds"
            hard_cap_seconds = max_seconds
            if warn_fraction is not None:
                assert warn_cap_seconds is None, "Cannot specify both warn_fraction and warn_cap_seconds"
                warn_cap_seconds = max_seconds * warn_fraction

        if hard_cap_dollars is not None:
            hard_cap_dollars = min(hard_cap_dollars, self.hard_cap_dollars)
        if hard_cap_seconds is not None:
            hard_cap_seconds = min(hard_cap_seconds, self.hard_cap_seconds)
        if warn_cap_dollars is not None:
            warn_cap_dollars = min(warn_cap_dollars, self.warn_cap_dollars)
        if warn_cap_seconds is not None:
            warn_cap_seconds = min(warn_cap_seconds, self.warn_cap_seconds)
        if dollars_per_hour is not None and self.dollars_per_hour is not None:
            dollars_per_hour = min(dollars_per_hour, self.dollars_per_hour)
        return ResourceLimits(
            hard_cap_dollars=hard_cap_dollars or self.hard_cap_dollars,
            hard_cap_seconds=hard_cap_seconds or self.hard_cap_seconds,
            warn_cap_dollars=warn_cap_dollars or self.warn_cap_dollars,
            warn_cap_seconds=warn_cap_seconds or self.warn_cap_seconds,
            dollars_per_hour=dollars_per_hour or self.dollars_per_hour,
            parent_limits=self,
        )

    def _get_excessive_spend_message(self, dollars: float, debug_info: Any = None) -> str:
        msg = f"Tried to spend {dollars} but only {self.hard_cap_dollars - self.dollars_spent} left (of {self.hard_cap_dollars})."
        if self.hard_cap_dollars == 0:
            msg += " You might want to set DEFAULT_MAX_HAMMER_DOLLARS to something non-zero"
        if debug_info is not None:
            msg += f"\nDebug info: {debug_info}"
        return msg

    async def authorize_spend(self, dollars: float, debug_info: Any | None = None) -> PaymentAuthorization:
        # note that we purposefully lock here, even though we are potentially waiting inside the loop below.
        # the reason for this is that otherwise a large transaction could be starved by a series of smaller transactions
        # this is annoying to reason about, so this makes it FIFO instead (though potentially at the cost of having to
        # wait for a while if you are near the limit and there are smaller transactions that could have made it through)
        async with self.spend_lock:
            await self._clear_old_authorizations()

            if self.dollars_spent + dollars > self.hard_cap_dollars:
                raise DollarLimitExceeded(self._get_excessive_spend_message(dollars, debug_info))

            # if we have outstanding authorizations that mean that this transaction would put us over the limit, wait
            while (await self.get_dollars_authorized_and_spent()) + dollars > self.hard_cap_dollars and (
                await self.get_dollars_currently_authorized()
            ) > 0:
                await self.next_settlement_event.wait()

            # now that some authorizations have settled and we're done waiting, have to check again if this would put us over
            if self.dollars_spent + dollars > self.hard_cap_dollars:
                raise DollarLimitExceeded(self._get_excessive_spend_message(dollars))

            dollars_per_hour = self.dollars_per_hour
            if dollars_per_hour is not None:
                if dollars > dollars_per_hour:
                    raise MaximumSpendExceeded(
                        f"Tried to spend ${dollars} but only ${dollars_per_hour} / hr allowed, which caps the total spend"
                    )

                # wait until the spend rate is low enough
                while (await self.get_dollars_authorized_and_spent_in_the_last_hour()) + dollars > dollars_per_hour:
                    oldest_event = first(
                        sorted(
                            [x for x in self.recent_spend_events],
                            key=lambda x: x.authorized_at,
                        )
                    )
                    if oldest_event is None:
                        break
                    time_since_oldest_event = (get_current_time() - oldest_event.authorized_at).total_seconds()
                    time_until_next_event_expires = _ONE_HOUR_IN_SECONDS - time_since_oldest_event
                    logger.debug(
                        f"Waiting until spend rate has subsided (currently at {(await self.get_dollars_authorized_and_spent_in_the_last_hour())} / hr)"
                    )
                    waiting_task = asyncio.create_task(self._wait_until_updated())
                    try:
                        await asyncio.wait_for(waiting_task, timeout=time_until_next_event_expires + 0.01)
                    except TimeoutError:
                        pass
                    await self._clear_old_authorizations()

                assert (await self.get_dollars_authorized_and_spent_in_the_last_hour()) + dollars <= dollars_per_hour

            async with self.state_lock:
                if self.parent_limits is None:
                    auth = PaymentAuthorization(
                        dollars=dollars,
                        authorization_id=uuid4().hex,
                        authorized_at=get_current_time(),
                    )
                else:
                    auth = await self.parent_limits.authorize_spend(dollars)
                self.open_authorizations[auth.authorization_id] = auth
                return auth

    async def settle_spend(self, authorization: PaymentAuthorization, dollars: float) -> None:
        async with self.state_lock:
            await self._clear_old_authorizations(_is_already_locked=True)

            if self.parent_limits is not None:
                await self.parent_limits.settle_spend(authorization, dollars)

            is_threshold_exceeded_by_this_transaction = (
                self.dollars_spent < self.warn_cap_dollars <= self.dollars_spent + dollars
            )

            if authorization.authorization_id not in self.open_authorizations:
                raise AuthorizationInvalidated(
                    f"Authorization {authorization.authorization_id} has timed out or already been settled"
                )
            del self.open_authorizations[authorization.authorization_id]
            self.recent_spend_events.append(authorization)
            self.dollars_spent += dollars
            assert self.save_spend_callback is not None, "Should have been initialized by now"
            await self.save_spend_callback(self.dollars_spent)

            # notify anything waiting on the next settlement
            self.next_settlement_event.set()
            self.next_settlement_event.clear()

            logger.trace(
                "Settled spend of {}, remaining: {}",
                dollars,
                self.hard_cap_dollars - self.dollars_spent,
            )

        if is_threshold_exceeded_by_this_transaction:
            await self._warn(f"Spent ${self.dollars_spent} already (will be stopped at ${self.hard_cap_dollars})")

    # TODO: make a more configurable warning system, right now just logs
    async def _warn(self, message: str) -> None:
        logger.warning(message)

    async def _clear_old_authorizations(self, _is_already_locked: bool = False) -> None:
        if not _is_already_locked:
            await self.state_lock.acquire()
        try:
            now = get_current_time()
            self.open_authorizations = {
                k: v
                for k, v in self.open_authorizations.items()
                if (now - v.authorized_at).total_seconds() < _AUTH_PAYMENT_TIMEOUT_SECONDS
            }
            self.recent_spend_events = [
                x for x in self.recent_spend_events if (now - x.authorized_at).total_seconds() < _ONE_HOUR_IN_SECONDS
            ]
        finally:
            if not _is_already_locked:
                self.state_lock.release()

    async def get_dollars_currently_authorized(self) -> float:
        async with self.state_lock:
            return sum(x.dollars for x in self.open_authorizations.values())

    async def get_dollars_authorized_and_spent(self) -> float:
        async with self.state_lock:
            dollars_currently_authorized = float(sum(x.dollars for x in self.open_authorizations.values()))
            return dollars_currently_authorized + self.dollars_spent

    async def get_dollars_authorized_and_spent_in_the_last_hour(self) -> float:
        async with self.state_lock:
            dollars_currently_authorized = float(sum(x.dollars for x in self.open_authorizations.values()))
            return dollars_currently_authorized + sum(x.dollars for x in self.recent_spend_events)

    async def bump_limits(self, limits: ResourceLimitState) -> ResourceLimitState:
        """
        Can only raise limits. This makes it easier for hammers to reason about how much they will be able to spend.

        If we were to allow reducing limits, we'd need to be quite careful to update existing timers, and to check
        conditions at the end of the wait loop in authorize_spend as well.
        """
        if self.parent_limits is None:
            assert limits.hard_cap_dollars < float("inf"), "Cannot unlimit spend for the top-level hammer"

        async with self.state_lock:
            self.hard_cap_dollars = max(self.hard_cap_dollars, limits.hard_cap_dollars)
            self.hard_cap_seconds = max(self.hard_cap_seconds, limits.hard_cap_seconds)
            self.warn_cap_dollars = max(self.warn_cap_dollars, limits.warn_cap_dollars)
            self.warn_cap_seconds = max(self.warn_cap_seconds, limits.warn_cap_seconds)
            if self.dollars_per_hour is None:
                self.dollars_per_hour = limits.dollars_per_hour
            else:
                if limits.dollars_per_hour is not None and limits.dollars_per_hour > self.dollars_per_hour:
                    self.dollars_per_hour = limits.dollars_per_hour

                    # notify anything waiting in case we just bumped what they were waiting on
                    if self.dollars_per_hour and limits.dollars_per_hour is not None:
                        self.limits_updated_event.set()
                        self.limits_updated_event.clear()

            return ResourceLimitState(
                hard_cap_dollars=self.hard_cap_dollars,
                hard_cap_seconds=self.hard_cap_seconds,
                warn_cap_dollars=self.warn_cap_dollars,
                warn_cap_seconds=self.warn_cap_seconds,
                dollars_per_hour=self.dollars_per_hour,
            )

    def resume(self, dollars: float, limits: ResourceLimitState) -> None:
        self.hard_cap_dollars = limits.hard_cap_dollars
        self.hard_cap_seconds = limits.hard_cap_seconds
        self.warn_cap_dollars = limits.warn_cap_dollars
        self.warn_cap_seconds = limits.warn_cap_seconds
        self.dollars_per_hour = limits.dollars_per_hour
        self.dollars_spent = dollars

        if self.dollars_spent > self.hard_cap_dollars:
            raise DollarLimitExceeded(
                f"Have already spent {self.dollars_spent} dollars (more than the hard cap of {self.hard_cap_dollars})"
            )

    async def _wait_until_updated(self) -> None:
        await self.limits_updated_event.wait()


@attr.s(auto_attribs=True)
class HammerTimer:
    limits: ResourceLimits
    timer_started_at: datetime.datetime
    timer_task: Task | None = None
    is_timeout_warning_issued: bool = False

    # TODO: need to save whether or not we warned about the time so that we dont warn again when resuming
    async def on_hammer_started(self, task_group: TaskGroup, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        seconds_ago = (get_current_time() - self.timer_started_at).total_seconds()
        possible_wait_times = [x - seconds_ago for x in [self.limits.hard_cap_seconds, self.limits.warn_cap_seconds]]
        positive_wait_times = [x for x in possible_wait_times if x > 0]
        if len(positive_wait_times) == 0:
            await callback()
            return
        time_until_limit_check = min(positive_wait_times)
        self.timer_task = task_group.create_task(self._timeout_after(time_until_limit_check, callback))

    async def on_hammer_stopped(self) -> None:
        # cancel the timer (if still running
        timer_task = self.timer_task
        if timer_task:
            safe_cancel(timer_task)
            try:
                await timer_task
            except CancelledError:
                pass
            self.timer_task = None

    async def _timeout_after(self, seconds: float, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        while True:
            await asyncio.sleep(seconds)

            # re-schedule ourselves for the next check if the limits have been updated, or we were just here for a warning
            time_since_started = (get_current_time() - self.timer_started_at).total_seconds()
            if time_since_started < self.limits.hard_cap_seconds:
                # emit a warning if necessary
                if time_since_started > self.limits.warn_cap_seconds and not self.is_timeout_warning_issued:
                    self.is_timeout_warning_issued = True
                    await self.limits._warn(
                        f"Taking longer than expected ({seconds} sec so far, will be killed at {self.limits.hard_cap_seconds}"
                    )
                # figure out how long to sleep for
                seconds = min(
                    [
                        self.limits.hard_cap_seconds - time_since_started,
                        self.limits.warn_cap_seconds - time_since_started,
                    ]
                )
                continue

            # if we're still here, we've timed out
            await callback()
            return


# Even if you don't use hammers, you can still benefit from having global resource limits.
# (When in hammer-less context, this global variable is checked by LanguageModelAPI. Only the financial limits are enforced.)

_GLOBAL_RESOURCE_LIMITS: ResourceLimits | None = None


def ensure_global_resource_limits(
    *,
    max_dollars: float | None = None,
    max_seconds: float | None = None,
    warn_fraction: float | None = None,
    dollars_per_hour: float | None = None,
    reset_if_already_set: bool = False,
) -> None:
    global _GLOBAL_RESOURCE_LIMITS
    if _GLOBAL_RESOURCE_LIMITS is None or reset_if_already_set:
        _GLOBAL_RESOURCE_LIMITS = ResourceLimits.build(
            max_dollars=max_dollars,
            max_seconds=max_seconds,
            warn_fraction=warn_fraction,
            dollars_per_hour=dollars_per_hour,
        )
        _GLOBAL_RESOURCE_LIMITS.save_spend_callback = _dummy_save_spend_callback


def get_global_resource_limits() -> ResourceLimits | None:
    return _GLOBAL_RESOURCE_LIMITS


async def _dummy_save_spend_callback(dollars: float) -> None:
    pass


async def get_global_resource_limits_summary() -> str:
    if _GLOBAL_RESOURCE_LIMITS is None:
        return "No global resource limits"
    output = [
        "Global resource limits summary:",
    ]
    max_dollars = _GLOBAL_RESOURCE_LIMITS.hard_cap_dollars
    amount_spent = await _GLOBAL_RESOURCE_LIMITS.get_dollars_authorized_and_spent()
    amount_remaining = max_dollars - amount_spent
    output.append(f"- Max dollars: ${max_dollars:.4f}")
    output.append(f"- Amount spent: ${amount_spent:.4f}")
    output.append(f"- Amount remaining: ${amount_remaining:.4f}")
    return "\n".join(output)
