"""Parse a deployed CloudFormation YAML template without dropping intrinsic tags."""

import yaml


class CloudFormationLoader(yaml.SafeLoader):
    pass


def intrinsic(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        if suffix == 'GetAtt':
            value = value.split('.', 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    key = suffix if suffix in {'Ref', 'Condition'} else 'Fn::' + suffix
    return {key: value}


CloudFormationLoader.add_multi_constructor('!', intrinsic)


def load_template(text):
    return yaml.load(text, Loader=CloudFormationLoader)
