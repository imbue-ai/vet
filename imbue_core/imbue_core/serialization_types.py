#  Related comment from Sam: "One of the reasons I don't really like using subclasses for things like this is that __init_subclass__ gets called before dataclass decorators are applied (so there's not really a great way to make sure that a class that inherits from Serializable is actually serializable). I think it's fine just as a marker for now, but might be worth thinking about at some point."
class Serializable:
    pass
