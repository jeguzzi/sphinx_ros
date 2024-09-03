def interface_reference(pkg: str, typ: str, name: str, version: str = "galactic") -> str:
    return f'http://docs.ros2.org/{version}/api/{pkg}/{typ}/{name}.html'
