from typing import (TYPE_CHECKING, Any, Dict, Iterable, List, Optional,
                    Tuple, Type, Union)
import warnings
from docutils import nodes
from docutils.nodes import Element
from sphinx.addnodes import pending_xref
from sphinx.domains import Domain, ObjType, Index
from sphinx.util.nodes import make_refnode
from sphinx.roles import XRefRole, EmphasizedLiteral
from sphinx.util.typing import RoleFunction

if TYPE_CHECKING:
    from sphinx.builders import Builder
    from sphinx.environment import BuildEnvironment

from .roles import PackageComponentRole, NodeComponentRole, InterfaceRole, FieldRole
from .directives import (
    ROSPackageDirective,
    ROSCurrentPackageDirective,
    RosMessageDirective,
    RosActionDirective,
    RosServiceDirective,
    ROSNodeDirective,
    ROSCurrentNodeDirective,
    ExecutableDirective,
    SubscriptionDirective,
    PublisherDirective,
    ServiceServerDirective,
    ServiceClientDirective,
    ActionServerDirective,
    ActionClientDirective,
    LaunchFileDirective,
    ModelDirective,
    ParameterDirective,
    RosAutoMessageDirective,
    RosAutoInterfacesDirective,
    RosAutoLaunchFileDirective,
    RosAutoServiceDirective,
    RosAutoActionDirective,
    NodeSummaryDirective,
    PackageSummaryDirective,
    GLTFDirective)
from .utils import interface_reference
# from .indices import RosPackageIndex, RosMessageIndex


class RosDomain(Domain):
    name = 'ros'
    label = 'ROS'
    object_types: Dict[str, ObjType] = {
        'node': ObjType('node', 'node', 'obj'),
        'parameter': ObjType('parameter', 'param', 'obj'),
        'subscription': ObjType('subscription', 'sub', 'obj'),
        'publisher': ObjType('publisher', 'pub', 'obj'),
        'service_client': ObjType('service_client', 'client', 'obj'),
        'service_server': ObjType('service_server', 'server', 'obj'),
        'action_client': ObjType('action_client', 'act_client', 'obj'),
        'action_server': ObjType('action_server', 'act_server', 'obj'),
        'package': ObjType('package', 'pkg', 'obj'),
        'executable': ObjType('executable', 'exec', 'obj'),
        'message': ObjType('message', 'msg', 'obj', 'interface'),
        'service': ObjType('service', 'srv', 'obj', 'interface'),
        'action': ObjType('action', 'act', 'obj', 'interface'),
        'launch_file': ObjType('launch_file', 'launch', 'obj'),
        'model': ObjType('model', 'model', 'obj')
    }
    roles: Dict[str, Union[RoleFunction, XRefRole]] = {
        'pkg': XRefRole(),
        'launch': PackageComponentRole(),
        'model': PackageComponentRole(),
        'exec': PackageComponentRole(),
        'msg': InterfaceRole(show_type='msg'),
        'srv': InterfaceRole(show_type='srv'),
        'action': InterfaceRole(show_type='action'),
        'node': XRefRole(),
        'param': NodeComponentRole(),
        'pub': NodeComponentRole(),
        'sub': NodeComponentRole(),
        'srv_client': NodeComponentRole(),
        'srv_server': NodeComponentRole(),
        'act_client': NodeComponentRole(),
        'act_server': NodeComponentRole(),
        'value': EmphasizedLiteral(),
        'field': FieldRole(show_container=True, show_type='msg')
    }
    directives: Dict[str, Any] = {
        'package': ROSPackageDirective,
        'currentpackage': ROSCurrentPackageDirective,
        'message': RosMessageDirective,
        'service': RosServiceDirective,
        'action': RosActionDirective,
        'node': ROSNodeDirective,
        'currentnode': ROSCurrentNodeDirective,
        'subscription': SubscriptionDirective,
        'publisher': PublisherDirective,
        'service_server': ServiceServerDirective,
        'service_client': ServiceClientDirective,
        'action_server': ActionServerDirective,
        'action_client': ActionClientDirective,
        'launch_file': LaunchFileDirective,
        'model': ModelDirective,
        'parameter': ParameterDirective,
        'automessage': RosAutoMessageDirective,
        'autointerfaces': RosAutoInterfacesDirective,
        'autolaunch_file': RosAutoLaunchFileDirective,
        'autoservice': RosAutoServiceDirective,
        'autoaction': RosAutoActionDirective,
        'executable': ExecutableDirective,
        'nodesummary': NodeSummaryDirective,
        'packagesummary': PackageSummaryDirective,
        'model-viewer': GLTFDirective
    }
    initial_data: Dict = {
        'objects': {},   # fullname -> docname, objtype
        'package': {},  # name -> document name, anchor, priority, deprecated
        'node': {},  # name -> document name, anchor, priority, deprecated
        'node_components': {},
        'package_components': {},
        'labels': {
            'ros-pkgindex': ('ros-pkgindex', '', 'Package Index'),
            'ros-msgindex': ('ros-msgindex', '', 'Message Type Index')
        },
        'anonlabels': {
            'ros-pkgindex': ('ros-pkgindex', ''),
            'ros-msgindex': ('ros-msgindex', '')
        }
    }
    indices: List[Type[Index]] = [
        # RosPackageIndex,
        # RosMessageIndex,
    ]

    def clear_doc(self, docname: str) -> None:
        for c in ('node', 'package'):
            for name, (fn, _) in list(self.data[c].items()):
                if fn == docname:
                    del self.data[c][name]
                cs = self.data[f'{c}_components'].get(name, {})
                for _, ls in cs.items():
                    for n, (f, _) in list(ls.items()):
                        if f == docname:
                            del ls[n]

    # override
    def resolve_xref(self, env: "BuildEnvironment", fromdocname: str, builder: "Builder",
                     typ: str, target: str, node: pending_xref, contnode: Element
                     ) -> Optional[Element]:
        # print('resolve_xref', typ, target, node, contnode, 'ros:node' in node)

        if typ == 'field':
            typ = 'msg'

        if typ in ('msg', 'srv', 'action'):
            package = node['ros:package']
            obj: Optional[Tuple[str, str]] = self.data['package_components'].get(package, {}).get(typ, {}).get(target)
            if obj:
                file_name, fullname = obj
                return make_refnode(builder, fromdocname, file_name, fullname, contnode, fullname)
            else:
                target = interface_reference(package, typ, target)
                ref_node = nodes.reference()
                ref_node['refuri'] = target
                ref_node += contnode
                return ref_node

        for container_type in ('node', 'package'):
            key = f'ros:{container_type}'
            if key in node:
                container = node.get(key)
                try:
                    file_name, fullname = self.data[f'{container_type}_components'][container][typ][target]
                except KeyError:
                    warnings.warn(f"Could not find {typ} {target} for {container_type} {container}")
                    return None
                return make_refnode(builder, fromdocname, file_name, fullname, contnode,
                                    fullname)

        if typ == 'pkg':
            typ = 'package'

        if typ in self.data and target in self.data[typ]:
            file_name, fullname = self.data[typ][target]
            return make_refnode(builder, fromdocname, file_name, fullname, contnode,
                                fullname)
        return None

    # TODO(Jerome) override
    def resolve_any_xref(self, env: "BuildEnvironment", fromdocname: str, builder: "Builder",
                         target: str, node: pending_xref, contnode: Element
                         ) -> List[Tuple[str, Element]]:
        return []

    # TODO(Jerome) override
    def get_objects(self) -> Iterable[Tuple[str, str, str, str, str, int]]:
        return []

    def add_container(self, name: str, typ: str) -> str:
        anchor = '.'.join((typ, name))
        self.data[typ][name] = (self.env.docname, anchor)
        return anchor

    def add_component(self, container_typ: str, container_name: str, typ: str, name: str) -> str:
        fullname = '.'.join((container_name, typ, name))
        value = (self.env.docname, fullname)
        if container_typ in ('package', 'node'):
            components = self.data[f'{container_typ}_components']
            components.setdefault(container_name, {}).setdefault(typ, {})[name] = value
        return fullname
