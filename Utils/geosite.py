import logging

from . import rule
from . import const


class Rule:
    Type: str
    Payload: str
    Tag: str

    def __init__(self):
        self.Type = ""
        self.Payload = ""
        self.Tag = ""

    def __str__(self):
        return f'Type: "{self.Type}", Payload: "{self.Payload}", Tag: "{self.Tag if self.Tag else ""}"'


def parse(src: set, excluded_imports: list = None) -> set:
    excluded_imports = [] if not excluded_imports else excluded_imports
    set_parsed = set()
    for raw_line in src:
        line = raw_line.split("#")[0].strip()
        if not line:
            continue
        parsed_rule = Rule()
        if "@" in line:
            parsed_rule.Tag = line.split("@")[1]
            line = line.split(" @")[0]
        if ":" not in line:
            parsed_rule.Type = "Suffix"
            parsed_rule.Payload = line
        elif line.startswith("full:"):
            parsed_rule.Type = "Full"
            parsed_rule.Payload = line.strip("full:")
        elif line.startswith("include:"):
            name_import = line.split("include:")[1]
            if name_import not in excluded_imports:
                logging.debug(f'Line "{raw_line}" is a import rule. Start importing "{name_import}".')
                src_import = set(
                    open(const.PATH_DOMAIN_LIST/name_import, mode="r", encoding="utf-8").read().splitlines())
                set_parsed |= parse(src_import, excluded_imports)
                logging.debug(f'Imported "{name_import}".')
                continue
            else:
                logging.debug(f'Line "{raw_line}" is a import rule, but hit exclusion "{name_import}", skipped.')
                continue
        else:
            logging.debug(f'Unsupported rule: "{raw_line}", skipped.')
            continue
        set_parsed.add(parsed_rule)
        logging.debug(f"Line {raw_line} is parsed: {parsed_rule}")
    return set_parsed


def convert(src: set, excluded_tags: list = None) -> set:
    excluded_tags = [] if not excluded_tags else excluded_tags
    set_converted = set()
    for input_rule in src:
        if input_rule.Tag not in excluded_tags:
            if input_rule.Type == "Suffix":
                set_converted.add("." + input_rule.Payload)
            elif input_rule.Type == "Full":
                set_converted.add(input_rule.Payload)
    return set_converted


def batch_convert(categories: list, tools: list, exclusions: list = None) -> None:
    exclusions = [] if not exclusions else exclusions
    for tool in tools:
        for category in categories:
            src_geosite = set(open(const.PATH_DOMAIN_LIST/category, mode="r", encoding="utf-8").read().splitlines())
            set_geosite = convert(parse(src_geosite, exclusions))
            list_geosite_sorted = rule.set_to_sorted_list(set_geosite)
            rule.dump(list_geosite_sorted, tool, const.PATH_DIST/tool/(category + ".txt"))
