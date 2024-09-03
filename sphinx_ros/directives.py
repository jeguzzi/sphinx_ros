import logging
import pathlib
import os
from functools import partial
from typing import Any, Dict, List, Optional, Tuple, cast, TYPE_CHECKING
import textwrap

from docutils import nodes
from docutils.parsers.rst import directives, Directive
from docutils.nodes import Node
from docutils.statemachine import StringList
from docutils.parsers.rst.states import Inliner

from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.addnodes import desc_signature
from sphinx.directives import ObjectDescription
from sphinx.environment import BuildEnvironment
from sphinx.util.nodes import make_refnode
from sphinx.util.typing import OptionSpec
from sphinx.util.docfields import Field, TypedField, GroupedField
from sphinx.util.docutils import SphinxDirective


from sphinx_design.icons import get_octicon

from sphinx_toolbox.collapse import CollapseNode

from ament_index_python.packages import get_package_share_directory
import rosidl_adapter.parser
from launch.launch_description_sources import get_launch_description_from_any_launch_file
from launch.actions.include_launch_description import IncludeLaunchDescription
import launch.substitutions
import launch_ros.substitutions

if TYPE_CHECKING:
    from sphinx.builders import Builder


def name_to_key(name: str) -> str:
    return name[0].upper()


def add_icon(icon: str, active: bool = True, title: str = '', uri: str = '') -> nodes.reference:
    icon_color = 'muted' if not active else 'primary'
    svg = get_octicon(icon, height="1em", classes=['sd-text-' + icon_color])
    node = nodes.raw("", nodes.Text(svg), format="html", title=title)
    ref_node = nodes.reference('', '', refuri=uri, reftitle=title)
    ref_node += node
    return ref_node


class ContainerDirective(ObjectDescription):

    has_content = True
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    typ: str

    option_spec: OptionSpec = {
        'deprecated': directives.flag,
        'summary': directives.flag,
        **ObjectDescription.option_spec
    }

    def before_content(self) -> None:
        name = self.arguments[0].strip()
        env = self.state.document.settings.env
        env.ref_context[f'ros:{self.typ}'] = name

    def transform_content(self, contentnode: addnodes.desc_content) -> None:
        if 'summary' in self.options:
            name = self.arguments[0].strip()
            contentnode += SummaryNode(name, title="Summary", typ=self.typ)

    def handle_signature(self, sig: str, signode: desc_signature) -> str:
        signode += addnodes.desc_annotation(self.typ, self.typ)
        signode += addnodes.desc_sig_space()
        signode += addnodes.desc_name(text=sig)
        return sig

    def add_target_and_index(self, name: str, sig: str, signode: desc_signature) -> None:
        fullname = self.env.get_domain('ros').add_container(sig, self.typ)   # type: ignore
        signode['ids'].append(fullname)
        return


class CurrentContainerDirective(Directive):

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec: OptionSpec = {}
    typ: str

    def run(self) -> List[Node]:
        env = self.state.document.settings.env
        name = self.arguments[0].strip()
        key = f'ros:{self.typ}'
        if name == 'None':
            env.ref_context.pop(key, None)
        else:
            env.ref_context[key] = name
        return []


class ROSPackageDirective(ContainerDirective):
    doc_field_types: List[Field] = []
    typ = 'package'


class ROSCurrentPackageDirective(CurrentContainerDirective):
    typ = 'package'


class ROSNodeDirective(ContainerDirective):
    doc_field_types: List[Field] = []
    typ = 'node'


class ROSCurrentNodeDirective(CurrentContainerDirective):
    typ = 'node'


def make_table(builder: "Builder", title: str, objects: Dict[str, Tuple[str, str]],
               file_name: str) -> nodes.table:
    table_node = nodes.table()
    tgroup = nodes.tgroup(cols=1)
    tgroup += nodes.colspec(colwidth=12)
    # tgroup += nodes.thead("", nodes.row("", nodes.entry("", nodes.paragraph("", title))))
    tbody = nodes.tbody()
    tgroup += tbody
    table_node += tgroup
    for name, (docname, fullname) in sorted(objects.items()):
        row = nodes.row()
        para = nodes.paragraph("", "")
        contnode = nodes.Text(name)
        ref = make_refnode(builder, file_name, docname, fullname, contnode, name)
        para += ref
        row += nodes.entry("", para)
        # row += nodes.entry("", nodes.paragraph("", name))
        tbody += row
    return table_node


class SummaryNode(nodes.General, nodes.Element):  # type: ignore

    HEADERS = {
        'param': 'Parameters',
        'sub': 'Subscriptions',
        'pub': 'Publishers',
        'srv_server': 'Service servers',
        'act_server': 'Action servers',
        'srv_client': 'Service clients',
        'act_client': 'Action clients',
        'exec': 'Executables',
        'msg': 'Messages',
        'srv': 'Services',
        'action': 'Actions',
        'launch': 'Launch files',
        'model': 'Models',
    }

    def __init__(self, rawsource: str, *children: Any, title: Optional[str] = None, typ: str = '',
                 **attributes: Any) -> None:
        super().__init__(rawsource, *children, **attributes)
        if title:
            self._title = title
        else:
            self._title = f'{typ.capitalize()} {rawsource} summary'
        self.typ = typ

    def process(self, app: Sphinx, docname: str) -> None:
        # TODO(Jerome: add css class -> background color)
        if not app.env:
            return
        s = nodes.admonition("")
        name = self.rawsource
        s += nodes.title("", '', nodes.Text(self._title))
        domain = app.env.get_domain('ros')
        components = domain.data[f'{self.typ}_components'].get(name, {})
        for (typ, title) in self.HEADERS.items():
            objects = components.get(typ, {})
            if not objects:
                continue
            c = CollapseNode(label=title, open=False)
            s += c
            if app.builder:
                table_node = make_table(app.builder, title, objects, docname)
                c += table_node
        self.replace_self(s)


def process_summaries(app: Sphinx, doctree: nodes.document, docname: str) -> None:
    for node in doctree.findall(SummaryNode):
        node.process(app, docname)


class NodeSummaryDirective(SphinxDirective):

    has_content = False
    required_arguments = 1
    optional_arguments = 1

    def run(self) -> List[Node]:
        return [SummaryNode(self.arguments[0], title=self.arguments[1], typ='node')]


class PackageSummaryDirective(SphinxDirective):

    has_content = False
    required_arguments = 1
    optional_arguments = 1

    def run(self) -> List[Node]:
        return [SummaryNode(self.arguments[0], title=self.arguments[1], typ='package')]


class ComponentDescription(ObjectDescription):

    has_content = True
    full_type = ''
    short_type = ''
    container_name: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.option_spec[self.container_name] = directives.unchanged
        self.key = f'ros:{self.container_name}'

    def get_container(self, sig: str) -> Tuple[str, str]:
        container = self.options.get(self.container_name, self.env.ref_context.get(self.key, ''))
        return container, sig

    def title(self, container: str, sig: str) -> str:
        return sig

    def handle_signature(self, sig: str, signode: desc_signature) -> Tuple[str, str]:
        container, sig = self.get_container(sig)
        signode += addnodes.desc_annotation(self.full_type, self.full_type)
        signode += addnodes.desc_sig_space()
        signode += addnodes.desc_name(text=self.title(container, sig))
        return container, sig

    def add_target_and_index(self, name_cls: Tuple[str, str], sig: str,
                             signode: desc_signature) -> None:
        container, sig = name_cls
        name = self.env.get_domain('ros').add_component(   # type: ignore
            self.container_name, container, self.short_type, sig)
        signode['ids'].append(name)


class PackageComponentDescription(ComponentDescription):
    container_name = 'package'


class RosTypedField(TypedField):

    def __init__(self, name: str, names: Tuple[str, ...] = (), typenames: Tuple[str, ...] = (),
                 label: Optional[str] = None, rolename: Optional[str] = None,
                 typerolename: str = 'field', can_collapse: bool = False) -> None:
        super().__init__(name, names, typenames, label, rolename, typerolename, can_collapse)  # type: ignore

    def make_field(self, types: Dict[str, List[Node]], domain: str,
                   items: Tuple, env: Optional[BuildEnvironment] = None,
                   inliner: Optional[Inliner] = None, location: Optional[Node] = None
                   ) -> nodes.field:
        def handle_item(fieldarg: str, content: str) -> nodes.paragraph:
            par = nodes.paragraph()
            par.extend(self.make_xrefs(cast(str, self.rolename), domain, fieldarg,
                                       addnodes.literal_strong, env=cast(BuildEnvironment, env)))
            if fieldarg in types:
                par += nodes.Text(' (')
                # NOTE: using .pop() here to prevent a single type node to be
                # inserted twice into the doctree, which leads to
                # inconsistencies later when references are resolved
                fieldtype = types.pop(fieldarg)
                # print('fieldtype', fieldtype)
                fieldvalue = None
                if len(fieldtype) == 1 and isinstance(fieldtype[0], nodes.Text):
                    typename = fieldtype[0].astext()
                    # print('typename', typename, typename.split('='))
                    r = typename.split('=')
                    if len(r) == 2:
                        typename, fieldvalue = r
                    par.extend(self.make_xrefs(
                        cast(str, self.typerolename), domain, typename, nodes.emphasis,
                        env=cast(BuildEnvironment, env), inliner=cast(Inliner, inliner),
                        location=cast(Node, location)))
                else:
                    par += fieldtype
                par += nodes.Text(')')
                if fieldvalue:
                    par += nodes.Text(' = ')
                    par += nodes.literal(fieldvalue, fieldvalue)

            par += nodes.Text(' -- ')
            par += content
            return par

        fieldname = nodes.field_name('', self.label)
        if len(items) == 1 and self.can_collapse:
            fieldarg, content = items[0]
            bodynode = handle_item(fieldarg, content)
        else:
            bodynode = self.list_type()
            for fieldarg, content in items:
                bodynode += nodes.list_item('', handle_item(fieldarg, content))
        fieldbody = nodes.field_body('', bodynode)
        return nodes.field('', fieldname, fieldbody)


class InterfaceDescription(PackageComponentDescription):

    def get_container(self, sig: str) -> Tuple[str, str]:
        container, sig = super().get_container(sig)
        rs = sig.split('/')
        if len(rs) == 2:
            container, sig = rs
        if len(rs) == 3:
            container, typ, sig = rs
            if typ != self.short_type:
                logging.warning(f"Malformed interface signature: expected {self.short_type}, got {typ}")
                return container, sig
        if len(rs) > 3:
            logging.warning(f"Malformed interface signature {sig}")
            return container, sig
        return container, sig

    def title(self, container: str, sig: str) -> str:
        return f"{container}/{self.short_type}/{sig}"


class RosActionDirective(InterfaceDescription):

    full_type = 'action'
    short_type = 'action'

    doc_field_types = [
        RosTypedField('goal_field',
                      label='Goal fields',
                      names=('goal_field',),
                      typenames=('goal_fieldtype',),
                      can_collapse=True),
        RosTypedField('result_field',
                      label='Result fields',
                      names=('result_field',),
                      typenames=('result_fieldtype',),
                      can_collapse=True),
        RosTypedField('feedback_field',
                      label='Feedback fields',
                      names=('feedback_field',),
                      typenames=('feedback_fieldtype',),
                      can_collapse=True),
        RosTypedField('goal_constant',
                      label='Goal constants',
                      names=('goal_const',),
                      typenames=('goal_consttype',),
                      can_collapse=True),
        RosTypedField('result_constant',
                      label='Result constants',
                      names=('result_const',),
                      typenames=('result_consttype',),
                      can_collapse=True),
        RosTypedField('feedback_constant',
                      label='Feedback constants',
                      names=('feedback_const',),
                      typenames=('feedback_consttype',),
                      can_collapse=True),
    ]


class RosServiceDirective(InterfaceDescription):

    full_type = 'service'
    short_type = 'srv'

    doc_field_types = [
        RosTypedField('req_field',
                      label='Request fields',
                      names=('req_field',),
                      typenames=('req_fieldtype',),
                      can_collapse=True),
        RosTypedField('resp_field',
                      label='Response fields',
                      names=('resp_field',),
                      typenames=('resp_fieldtype',),
                      can_collapse=True),
        RosTypedField('req_constant',
                      label='Request constants',
                      names=('req_const',),
                      typenames=('req_consttype',),
                      can_collapse=True),
        RosTypedField('resp_constant',
                      label='Response constants',
                      names=('resp_const',),
                      typenames=('resp_consttype',),
                      can_collapse=True),
    ]


class RosMessageDirective(InterfaceDescription):

    full_type = 'message'
    short_type = 'msg'

    option_spec: OptionSpec = {
        'noindex': directives.flag,
        'package': directives.unchanged,
        'deprecated': directives.flag,
    }
    # option_spec['deprecated'] = directives.flag

    doc_field_types = [
        RosTypedField('field',
                      label='Fields',
                      names=('field',),
                      typenames=('fieldtype',),
                      can_collapse=True),
        RosTypedField('constant',
                      label='Constants',
                      names=('const',),
                      # typerolename='value',
                      typenames=('consttype',),
                      can_collapse=True),
    ]

    # def add_object_to_domain_data(self, fullname, obj_type):
    #     ros_domain = self.env.get_domain('ros')
    #     ros_domain.add_message(fullname, 'deprecated' in self.options)


def load_interface(package: str, typ: str, interface_name: str) -> Any:
    interface_location = pathlib.Path(
        get_package_share_directory(package)) / typ / (interface_name + '.' + typ)
    if typ == 'msg':
        return rosidl_adapter.parser.parse_message_file(package, interface_location)
    if typ == 'srv':
        return rosidl_adapter.parser.parse_service_file(package, interface_location)
    if typ == 'action':
        return rosidl_adapter.parser.parse_action_file(package, interface_location)


def import_message(message: Any, field_name: str, const_name: str) -> StringList:
    lines = []
    current_line = ''
    for line in message.annotations['comment']:
        if line:
            if current_line:
                if line[0].isupper() and current_line[-1] != '.':
                    current_line += '.'
                current_line += ' '
                current_line += line
            else:
                current_line = line
        elif current_line:
            if current_line[-1] != '.':
                current_line += '.'
            lines.append(current_line)
            lines.append('')
            current_line = ''
    lines.append(current_line)
    lines.append('')
    for member in message.fields:
        # print(member.type, member.name)
        comment = ' '.join(member.annotations['comment'])
        default_value = member.default_value
        if member.type.is_primitive_type():
            type_name = member.type.type
        else:
            type_name = '/'.join([member.type.pkg_name, member.type.type])
        if member.type.is_array:
            if member.type.is_primitive_type():
                type_name = f"{type_name}[{member.type.array_size or ''}]"
            else:
                type_name = f":ros:field:`{type_name}` [{member.type.array_size or ''}]"
        if default_value is not None:
            typevalue = f'={default_value}'
        else:
            typevalue = ''
        lines.append(f':{field_name} {member.name}: {comment}')
        lines.append(f':{field_name}type {member.name}: {type_name}{typevalue}')
    for const in message.constants:
        comment = ' '.join(const.annotations['comment'])
        lines.append(f':{const_name} {const.name}: {comment}')
        lines.append(f':{const_name}type {const.name}: {const.type}={const.value}')
    return StringList(lines)


#  TODO(Jerome) how to type mixins?
class RosAutoInterfaceDirective:

    required_arguments = 1

    def before_content(self) -> None:
        package, type_, interface_name = self.arguments[0].split('/')  # type: ignore
        interface = load_interface(package, type_, interface_name)
        self.content = self.import_interface(interface)
        self.name = self.name.replace('auto', '')  # type: ignore

    def import_interface(self, interface: str) -> Any:
        ...

    def run(self) -> List[Node]:
        self.name = self.name.replace('auto', '')
        return super().run()  # type: ignore


class RosAutoMessageDirective(RosAutoInterfaceDirective, RosMessageDirective):

    def import_interface(self, msg: Any) -> Any:
        return import_message(msg, 'field', 'const')


class RosAutoServiceDirective(RosAutoInterfaceDirective, RosServiceDirective):

    def import_interface(self, srv: Any) -> Any:
        return (import_message(srv.request, 'req_field', 'req_const') +
                import_message(srv.response, 'resp_field', 'resp_const'))


class RosAutoActionDirective(RosAutoInterfaceDirective, RosActionDirective):

    def import_interface(self, action: Any) -> Any:
        return (import_message(action.goal, 'goal_field', 'goal_const') +
                import_message(action.result, 'result_field', 'result_const') +
                import_message(action.feedback, 'feedback_field', 'feedback_const'))


class RosAutoInterfacesDirective(Directive):
    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {
        'messages': directives.unchanged,
        'services': directives.unchanged,
        'actions': directives.unchanged,
        'title_level': partial(directives.choice, values='"^-=*#')
    }

    def run(self) -> List[Node]:
        package = self.arguments[0]
        lines = []
        for type_, name in (('msg', 'message'), ('srv', 'service'), ('action', 'action')):
            title = self.options.get(f'{name}s')
            underline = self.options.get('title_level', '') or '"'
            if title is None:
                continue
            if title:
                lines.append(title)
                lines.append(underline * len(title))
                lines.append('')
            dir_path = pathlib.Path(get_package_share_directory(package)) / pathlib.Path(type_)
            extension = '.' + type_
            for interface_file in sorted(os.listdir(dir_path)):
                if interface_file.endswith(extension):
                    interface_file = interface_file.split(extension)[0]
                    lines.append(f'.. ros:auto{name}:: {package}/{type_}/{interface_file}')
                    lines.append('')
        node = nodes.Element()
        node.document = self.state.document
        self.state.nested_parse(StringList(lines), self.content_offset,
                                node, match_titles=1)
        return node.children


def _value(v: Any) -> str:
    if isinstance(v, launch.substitutions.text_substitution.TextSubstitution):
        return v.text
    if isinstance(v, launch.substitutions.python_expression.PythonExpression):
        return ''.join(_value(w) for w in v.expression)
    if isinstance(v, launch.substitutions.launch_configuration.LaunchConfiguration):
        return '<' + ''.join(_value(w) for w in v.variable_name) + '>'
    if isinstance(v, launch_ros.substitutions.find_package.FindPackageShare):
        return 'pkg_share(' + ''.join(_value(w) for w in v.package) + ')'
    else:
        print('not implemented', type(v))
    return ''


def include_redefine_argument(include_desc: IncludeLaunchDescription, name: str) -> bool:
    for x, y in include_desc.launch_arguments:
        if x[0].text == name:
            return True
    return False

def parse_launch_file(path: str) -> List[str]:
    launch_description = get_launch_description_from_any_launch_file(str(path))
    arguments = launch_description.get_launch_arguments_with_include_launch_description_actions()
    lines = []
    for argument, includes in arguments:
        if includes:
            redefine = any(include_redefine_argument(include, argument.name)
                           for include in includes)
            if redefine:
                # we don't include arguments that are inherited but redefined
                # as they are not accessible
                continue
        desc = argument.description
        if argument.default_value is not None:
            default = ''.join(_value(x) for x in argument.default_value)
            if not default:
                default = '""'
            default = f'[Default: ``{default}``]'
        else:
            default = ''
        if desc == 'no description given':
            desc = ''
        lines.append(f'  :arg {argument.name}: {desc} {default}')
    return lines


def indent(value: StringList, prefix: str = '  ') -> StringList:
    return StringList([textwrap.indent(text, prefix) for text in value])


class RosAutoLaunchFileDirective(Directive):
    has_content = True
    required_arguments = 2
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec: OptionSpec = {}

    def run(self) -> List[Node]:
        package, launch_file_name = self.arguments
        path = pathlib.Path(get_package_share_directory(package)) / 'launch' / pathlib.Path(launch_file_name)
        lines = []
        lines.append(f'.. ros:launch_file:: {launch_file_name}')
        lines.append('')
        header = StringList(lines)
        lines = ['']
        lines += parse_launch_file(str(path))
        node = nodes.Element()
        node.document = self.state.document
        fields = StringList(lines)
        self.state.nested_parse(header + indent(self.content, '  ') + fields, self.content_offset,
                                node, match_titles=1)
        return node.children


class ExecutableDirective(PackageComponentDescription):
    required_arguments = 1
    optional_arguments = 1
    full_type = 'executable'
    short_type = 'exec'

    def handle_signature(self, sig: str, signode: desc_signature) -> Tuple[str, str]:
        container, sig = super().handle_signature(sig, signode)
        if len(self.arguments) == 2:
            signode += addnodes.desc_sig_space()
            signode += addnodes.desc_inline('', text=self.arguments[-1])
        return container, sig

    doc_field_types = [
        GroupedField(
            'argument',
            label='Positional arguments',
            names=('arg', 'argument'),
            can_collapse=True),
        GroupedField(
            'option',
            label='Optional arguments',
            names=('opt', 'option'),
            can_collapse=True)
    ]


class LaunchFileDirective(PackageComponentDescription):
    required_arguments = 1
    full_type = 'launch file'
    short_type = 'launch'

    doc_field_types = [
        GroupedField(
            'argument',
            label='Arguments',
            names=('arg', 'argument'),
            # typerolename='obj',
            # typenames=('arg_type', 'argument_type'),
            can_collapse=False)
    ]


class ModelDirective(PackageComponentDescription):
    required_arguments = 1
    full_type = 'model'
    short_type = 'model'

    doc_field_types = [
        TypedField('argument',
                   label='Arguments',
                   names=('arg', 'argument'),
                   # typerolename='obj',
                   typenames=('arg_type', 'argument_type'),
                   can_collapse=True),
    ]


class NodeComponentDescription(ComponentDescription):
    container_name = 'node'


class ParameterDirective(NodeComponentDescription):
    required_arguments = 2
    full_type = 'parameter'
    short_type = 'param'
    option_spec = {
        'dynamic': directives.flag,
        'readonly': directives.flag,
        'default': directives.unchanged,
    }

    def handle_signature(self, sig: str, signode: desc_signature) -> Tuple[str, str]:
        ros_node, sig = super().handle_signature(sig, signode)
        signode += addnodes.desc_sig_space()
        signode += addnodes.desc_type(text=self.arguments[1])
        if 'default' in self.options:
            default_value = self.options['default']
            signode += addnodes.desc_sig_space()
            signode += nodes.Text('[Default: ')
            signode += nodes.literal(default_value, default_value)
            signode += nodes.Text(']')
        if 'dynamic' in self.options:
            signode += addnodes.desc_sig_space()
            signode += add_icon('sync', active=True, title='Dynamic', uri='')
        if 'readonly' in self.options:
            signode += addnodes.desc_sig_space()
            signode += add_icon('lock', active=True, title='Read only', uri='')
        return ros_node, sig


def qos_reliability(value: str) -> str:
    if value.lower() in ('best effort', 'best_effort', 'be'):
        return 'best_effort'
    if value.lower() in ('reliable', 're'):
        return 'reliable'
    if value.strip() == '':
        return ''
    raise ValueError(f"Unknown qos reliablity value {value}")


def qos_durability(value: str) -> str:
    if value.lower() in ('volatile', 'vo'):
        return 'volatile'
    if value.lower() in ('transient_local', 'transient local', 'transient', 'tl', 'tr'):
        return 'transient_local'
    if value.strip() == '':
        return ''
    raise ValueError(f"Unknown qos durability value {value}")


class CommunicationDescription(NodeComponentDescription):

    interface_role = ''

    option_spec = {
        'qos-reliability': qos_reliability,
        'qos-durability': qos_durability,
    }

    QOS = 'https://docs.ros.org/en/humble/Concepts/About-Quality-of-Service-Settings.html#qos-policies'

    def interface_reference(self, target: str) -> Node:
        # nodes, _ = InterfaceRole()(name=self.interface_role, rawtext=target, text=target,
        #                            lineno=0, inliner=self.state.inliner)
        node = nodes.Element()
        node.document = self.state.document
        lines = [f':ros:{self.interface_role}:`{target}`']
        self.state.nested_parse(StringList(lines), self.content_offset, node, match_titles=1)
        return node.children[0].children[0]
        # type_node = addnodes.desc_type(text=self.arguments[1])
        # type_node['classes'] = ['xref', 'ros', 'ros-' + self.interface_role]
        # ref_node = addnodes.pending_xref(
        #     '', type_node, refdomain='ros', reftype=self.interface_role, reftarget=target)
        #
        # return ref_node

    def handle_signature(self, sig: str, signode: desc_signature) -> Tuple[str, str]:
        ros_node, sig = super().handle_signature(sig, signode)
        signode += addnodes.desc_sig_space()
        signode += self.interface_reference(self.arguments[1])
        qos_rel = self.options.get('qos-reliability', '')
        qos_dur = self.options.get('qos-durability', '')
        if qos_rel:
            signode += addnodes.desc_sig_space()
            signode += add_icon('check-circle', active=(qos_rel == 'reliable'),
                                title=f'Reliability: {qos_rel}', uri=self.QOS)
        if qos_dur:
            signode += addnodes.desc_sig_space()
            signode += add_icon('pin', active=(qos_dur == 'transient_local'),
                                title=f'Durability: {qos_dur}', uri=self.QOS)
        return ros_node, sig


class SubscriptionDirective(CommunicationDescription):
    required_arguments = 2
    full_type = 'subscription'
    short_type = 'sub'
    interface_role = 'msg'


class PublisherDirective(CommunicationDescription):
    required_arguments = 2
    full_type = 'publisher'
    short_type = 'pub'
    interface_role = 'msg'


class ServiceClientDirective(CommunicationDescription):
    required_arguments = 2
    full_type = 'service client'
    short_type = 'srv_client'
    interface_role = 'srv'


class ServiceServerDirective(CommunicationDescription):
    required_arguments = 2
    full_type = 'service server'
    short_type = 'srv_server'
    interface_role = 'srv'


class ActionClientDirective(CommunicationDescription):
    required_arguments = 2
    full_type = 'action client'
    short_type = 'act_client'
    interface_role = 'action'


class ActionServerDirective(CommunicationDescription):
    required_arguments = 2
    full_type = 'action server'
    short_type = 'act_server'
    interface_role = 'action'

class GLTFNode(nodes.General, nodes.Element):  # type: ignore
    pass

def visit_gltf_node(self, node: GLTFNode) -> None:
    self.body.append(
    '<div><script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>'
    ' <model-viewer style="background-color: #777777; width: 600px; height: 400px;"'
    ' camera-controls touch-action="pan-y" alt=""'
    f' src="_static/gltf/{node.rawsource}" shadow-intensity="0.9" shadow-softness="0.2" /></div>')


def depart_gltf_node(self, node: GLTFNode) -> None:
    pass
    # self.body.append('</model-viewer>')


class GLTFDirective(SphinxDirective):

    has_content = False
    required_arguments = 1
    optional_arguments = 0

    def run(self) -> List[Node]:
        return [GLTFNode(self.arguments[0])]
