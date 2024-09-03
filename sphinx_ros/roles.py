import re
from typing import TYPE_CHECKING, Tuple, List, Optional, Type

from docutils import nodes
from docutils.nodes import Element, Node, TextElement, system_message
from sphinx.roles import XRefRole

import logging

if TYPE_CHECKING:
    from sphinx.environment import BuildEnvironment


class ComponentRole(XRefRole):

    innernodeclass = nodes.emphasis

    key: str = ''
    sep: str = '/'
    show_container = False
    show_type = ''

    def __init__(self, fix_parens: bool = False, lowercase: bool = False,
                 nodeclass: Optional[Type[Element]] = None,
                 innernodeclass: Optional[Type[TextElement]] = None,
                 warn_dangling: bool = False,
                 show_container: Optional[bool] = None,
                 show_type: Optional[str] = None) -> None:
        super().__init__(fix_parens, lowercase, nodeclass, innernodeclass, warn_dangling)  # type: ignore
        if show_container is not None:
            self.show_container = show_container
        if show_type is not None:
            self.show_type = show_type

    def get_container(self, parts: List[str]) -> Tuple[str, str]:
        if len(parts) == 2:
            value, target = parts
        else:
            value = ''
            target = parts[0]
        return target, value

    def get_title(self, title: str, target: str, container: str) -> str:
        show_container = False
        if self.show_container:
            show_container = not title.startswith('~')
        else:
            show_container = title.startswith('@')
        if show_container and container:
            return self.sep.join((x for x in (container, self.show_type, target) if x))
        return target

    def get_target(self, target: str) -> str:
        return target

    def process_link(self, env: "BuildEnvironment", refnode: Element, has_explicit_title: bool,
                     title: str, target: str) -> Tuple[str, str]:
        if not has_explicit_title:
            target = target.lstrip('~@')
        target, value = self.get_container(target.split(self.sep))
        if value:
            refnode['ros:explicit_container'] = True
        else:
            value = env.ref_context.get(self.key, '')
            refnode['ros:explicit_container'] = False
        refnode[self.key] = value
        target = self.get_target(target)
        if not has_explicit_title:
            title = self.get_title(title, target, value)
        return title, target


class NodeComponentRole(ComponentRole):
    key = 'ros:node'
    sep = ':'


class PackageComponentRole(ComponentRole):
    key = 'ros:package'
    sep = '/'


class InterfaceRole(PackageComponentRole):

    show_container = True

    def get_container(self, parts: List[str]) -> Tuple[str, str]:
        if len(parts) == 2:
            value, target = parts
        elif len(parts) == 3:
            value, typ, target = parts
            if typ != self.show_type:
                logging.error(f"Got different interface type {typ} vs {self.show_type}")
        else:
            value = ''
            target = parts[0]
        return target, value

    def get_target(self, target: str) -> str:
        # remove array from obj
        rs = re.split(r'\[<?=?\d*\]$', target)
        if len(rs) == 2:
            target = rs[0]
        # remove string length
        rs = re.split(r'<=\d+$', target)
        if len(rs) == 2 and rs[0] in ('string', 'wstring'):
            target = rs[0]
        return target


class FieldRole(InterfaceRole):

    primitives = [
        'bool', 'byte', 'char', 'float32', 'float64', 'int8', 'uint8', 'int16', 'uint16',
        'int32', 'uint32', 'int64', 'uint64', 'string', 'wstring']

    PRIMITIVE_URL = "https://docs.ros.org/en/humble/Concepts/About-ROS-Interfaces.html#field-types"

    def process_link(self, env: "BuildEnvironment", refnode: Element, has_explicit_title: bool,
                     title: str, target: str) -> Tuple[str, str]:
        new_title, target = super().process_link(env, refnode, has_explicit_title, title, target)
        refnode["ros:primitive"] = (target in self.primitives)
        if not refnode["ros:primitive"]:
            title = new_title
        return title, target

    def result_nodes(self, document: nodes.document, env: "BuildEnvironment", node: Element,
                     is_ref: bool) -> Tuple[List[Node], List[system_message]]:

        if node["ros:primitive"] and is_ref:
            ref_node = nodes.reference()
            ref_node['refuri'] = self.PRIMITIVE_URL
            text_node = nodes.emphasis(text=node.astext())
            text_node['classes'] = ['xref', 'ros', 'ros-primitive']
            ref_node += text_node
            return [ref_node], []
        return super().result_nodes(document, env, node, is_ref)
