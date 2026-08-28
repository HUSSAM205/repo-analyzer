def greet(name):
    return f"Hello, {name}!"


class Greeter:
    def __init__(self, default_name="World"):
        self.default_name = default_name

    def greet_default(self):
        return greet(self.default_name)
