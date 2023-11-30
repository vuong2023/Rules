import json
import logging
from copy import deepcopy
from ipaddress import ip_network
from pathlib import Path

from . import const


class Rule:
    Type: str  # DomainSuffix / DomainFull / IPCIDR / IPCIDR6
    Payload: str
    Tag: str

    def __init__(self, rule_type: str = "", payload: str = "", tag: str = ""):
        if rule_type or payload:
            self.set_type(rule_type)
            self.set_payload(payload)
            self.set_tag(tag)
        else:
            self.Type = ""
            self.Payload = ""
            self.Tag = tag

    def __str__(self):
        return f'Type: "{self.Type}", Payload: "{self.Payload}", Tag: {self.Tag if self.Tag else "NONE"}'

    def __hash__(self):
        return hash(("type" + self.Type, "payload" + self.Payload))

    def __eq__(self, other):
        return self.Type == other.Type and self.Payload == other.Payload

    def set_type(self, rule_type: str):
        allowed_type = ("DomainSuffix", "DomainFull", "IPCIDR", "IPCIDR6")
        if rule_type not in allowed_type:
            raise TypeError(f"Unsupported type: {rule_type}")
        self.Type = rule_type

    def set_payload(self, payload: str):
        if "Domain" in self.Type:
            if not is_domain(payload):
                raise ValueError(f"Invalid domain: {payload}")
        elif "IP" in self.Type:
            try:
                ip_network(payload)
            except ValueError:
                raise ValueError(f"Invalid IP address: {payload}")
        self.Payload = payload

    def set_tag(self, tag: str = ""):
        self.Tag = tag

    def includes(self, other):
        if self.Type == "DomainSuffix":
            if self.Payload == other.Payload:
                return True
            return other.Payload.endswith("." + self.Payload)
        elif self.Type == "DomainFull":
            return self == other


class RuleSet:
    Type: str  # Domain / IPCIDR / Combined
    Payload: list[Rule]

    def __init__(self, ruleset_type: str, payload: list):
        if ruleset_type or payload:
            self.set_type(ruleset_type)
            self.set_payload(payload)
        else:
            self.Type = ""
            self.Payload = []

    def __hash__(self):
        return hash(self.Type) + hash(self.Payload)

    def __eq__(self, other):
        return self.Type == other.Type and self.Payload == other.Payload

    def __len__(self):
        return len(self.Payload)

    def __or__(self, other):
        for rule in other.Payload:
            if rule not in self.Payload:
                self.Payload.append(rule)
        return self

    def __contains__(self, item):
        return item in self.Payload

    def __iter__(self):
        return iter(self.Payload)

    def set_type(self, ruleset_type):
        allowed_type = ("Domain", "IPCIDR", "Combined")
        if ruleset_type not in allowed_type:
            raise TypeError(f"Unsupported type: {ruleset_type}")
        self.Type = ruleset_type

    def set_payload(self, payload):
        match self.Type:
            case "Domain":
                for item in payload:
                    if "Domain" not in item.Type:
                        raise ValueError(f"{item.Type}-type rule found in a domain-type ruleset.")
            case "IPCIDR":
                for item in payload:
                    if "IPCIDR" not in item.Type:
                        raise ValueError(f"{item.Type}-type rule found in a IPCIDR-type ruleset.")
            case "Combined":
                for item in payload:
                    if item.Type not in ("DomainSuffix", "DomainFull", "IPCIDR", "IPCIDR6", "Classical"):
                        raise ValueError(f"{item.Type}-type rule found in a classical-type ruleset.")
        self.Payload = payload

    def deepcopy(self):
        return deepcopy(self)

    def add(self, rule):
        self.Payload.append(rule)

    def remove(self, rule):
        self.Payload.remove(rule)

    def sort(self):
        if self.Type == "Combined":
            logging.warning("Combined-type ruleset shouldn't be sorted as maybe ordered, skipped.")
            return

        def sort_key(item):
            match item.Type:
                # Domain suffixes should always in front of full domains
                # Shorter domains should in front of longer domains
                # For IPCIDR ruleset, default sort method is ok.
                case "DomainSuffix":
                    sortkey = (0, len(item.Payload), item.Payload)
                case "DomainFull":
                    sortkey = (1, len(item.Payload), item.Payload)
                case _:
                    sortkey = item.Payload
            return sortkey
        self.Payload.sort(key=sort_key)

    def dedup(self):
        self.sort()
        list_unique = []
        for item in self:
            flag_unique = True
            for added in list_unique:
                if added.includes(item):
                    flag_unique = False
                    logging.debug(f"{item} is removed as duplicated with {added}.")
            if flag_unique:
                list_unique.append(item)
        self.Payload = list_unique


def custom_convert(src: Path) -> RuleSet:
    src_custom = open(src, mode="r", encoding="utf-8").read().splitlines()
    try:
        ruleset_type = src_custom[0].split("@")[1]
    except IndexError:
        logging.warning(f"File {src} doesn't have a valid type header, treat as domain type.")
        ruleset_type = "Domain"
    ruleset_converted = RuleSet(ruleset_type, [])
    match ruleset_type:
        case "Domain":
            for line in src_custom:
                if line.startswith("."):
                    ruleset_converted.add(Rule("DomainSuffix", line.strip(".")))
                elif line and not line.startswith("#"):
                    ruleset_converted.add(Rule("DomainFull", line))
        case "IPCIDR":
            for line in src_custom:
                if line and not line.startswith("#"):
                    if ":" in line:
                        ruleset_converted.add(Rule("IPCIDR6", line))
                    else:
                        ruleset_converted.add(Rule("IPCIDR", line))
        case "Combined":
            for line in src_custom:
                if line and not line.startswith("#"):
                    parsed = line.split(",")
                    match parsed[0]:
                        case "DOMAIN":
                            ruleset_converted.add(Rule("DomainFull", parsed[1]))
                        case "DOMAIN-SUFFIX":
                            ruleset_converted.add(Rule("DomainSuffix", parsed[1]))
                        case "IP-CIDR":
                            ruleset_converted.add(Rule("IPCIDR", parsed[1]))
                        case "IP-CIDR6":
                            ruleset_converted.add(Rule("IPCIDR6", parsed[1]))
                        case _:
                            raise ValueError()
    return ruleset_converted


def is_ipv4addr(addr: str) -> bool:
    if addr.count(".") != 3:
        return False
    for part in addr.split("."):
        if not part.isdigit():
            return False
        i = int(part)
        if i < 0 or i > 255:
            return False
    return True


def is_domain(addr: str) -> bool:
    blacklist_include = ("/", "*", "=", "~", "?", "#", ",", ":", " ", "(", ")", "[", "]", "_", "|", "@", "^")
    if (any([bl_char in addr for bl_char in blacklist_include])
            or addr.startswith("-")
            or addr.endswith(".")
            or addr.endswith("-")
            or is_ipv4addr(addr)):
        return False
    return True


def dump(src: RuleSet, target: str, dst: Path, filename: str) -> None:
    try:
        if target == "yaml":
            filename = filename + ".yaml"
        elif target == "geosite":
            if src.Type == "IPCIDR" or src.Type == "Combined":
                logging.warning(f"{filename}: {src.Type}-type ruleset can't be exported to GeoSite source, ignored.")
                return
            filename = filename
        elif target == "sing-ruleset":
            filename = filename + ".json"
        else:
            if "text" in target and src.Type == "Combined":
                logging.info(f"{filename}: Combined-type ruleset doesn't need to exported as plain text, skipped.")
                return
            filename = filename + ".txt"
        dist = open(dst/filename, mode="w", encoding="utf-8")
    except FileNotFoundError:
        dst.mkdir(parents=True)
        dist = open(dst/filename, mode="w")
    match target:
        case "text":
            for rule in src:
                if rule.Type == "DomainSuffix":
                    dist.writelines(f".{rule.Payload}\n")
                elif rule.Type == "DomainFull" or "IPCIDR" or "IPCIDR6":
                    dist.writelines(f"{rule.Payload}\n")
                else:
                    raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
        case "text-plus":
            for rule in src:
                if rule.Type == "DomainSuffix":
                    dist.writelines(f"+.{rule.Payload}\n")
                elif rule.Type == "DomainFull" or "IPCIDR" or "IPCIDR6":
                    dist.writelines(f"{rule.Payload}\n")
                else:
                    raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
        case "yaml":
            dist.writelines("payload:\n")
            for rule in src:
                if rule.Type == "DomainSuffix":
                    dist.writelines(f"  - '+.{rule.Payload}'\n")
                elif rule.Type == "DomainFull" or "IPCIDR" or "IPCIDR6":
                    dist.writelines(f"  - '{rule.Payload}'\n")
                else:
                    raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
        case "surge-compatible":
            for rule in src:
                match rule.Type:
                    case "DomainSuffix":
                        dist.writelines(f"DOMAIN-SUFFIX,{rule.Payload}\n")
                    case "DomainFull":
                        dist.writelines(f"DOMAIN,{rule.Payload}\n")
                    case "IPCIDR":
                        dist.writelines(f"IP-CIDR,{rule.Payload}\n")
                    case "IPCIDR6":
                        dist.writelines(f"IP-CIDR6,{rule.Payload}\n")
                    case _:
                        raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
        case "clash-compatible":
            for rule in src:
                match rule.Type:
                    case "DomainSuffix":
                        dist.writelines(f"DOMAIN-SUFFIX,{rule.Payload},Policy\n")
                    case "DomainFull":
                        dist.writelines(f"DOMAIN,{rule.Payload},Policy\n")
                    case "IPCIDR":
                        dist.writelines(f"IP-CIDR,{rule.Payload},Policy\n")
                    case "IPCIDR6":
                        dist.writelines(f"IP-CIDR6,{rule.Payload},Policy\n")
                    case _:
                        raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
        case "geosite":
            for rule in src:
                match rule.Type:
                    case "DomainSuffix":
                        dist.writelines(f"{rule.Payload}\n")
                    case "DomainFull":
                        dist.writelines(f"full:{rule.Payload}\n")
                    case _:
                        raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
        case "sing-ruleset":
            ruleset = {
                "version": 1,
                "rules": [
                    {}
                ]
            }
            match src.Type:
                case "Domain":
                    for rule in src:
                        match rule.Type:
                            case "DomainSuffix":
                                if "domain_suffix" not in ruleset["rules"][0]:
                                    ruleset["rules"][0]["domain_suffix"] = []
                                ruleset["rules"][0]["domain_suffix"].append(f".{rule.Payload}")
                            case "DomainFull":
                                if "domain" not in ruleset["rules"][0]:
                                    ruleset["rules"][0]["domain"] = []
                                ruleset["rules"][0]["domain"].append(rule.Payload)
                            case _:
                                raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
                    dist.write(json.dumps(ruleset, indent=2))
                case "IPCIDR":
                    for rule in src:
                        if rule.Type not in ["IPCIDR", "IPCIDR6"]:
                            raise TypeError(f'Unsupported rule type "{rule.Type}". File: {dst}.')
                        if "ip_cidr" not in ruleset["rules"][0]:
                            ruleset["rules"][0]["ip_cidr"] = []
                        ruleset["rules"][0]["ip_cidr"].append(rule.Payload)
                    dist.write(json.dumps(ruleset, indent=2))
                case "Combined":
                    for rule in src:
                        match rule.Type:
                            case "DomainFull":
                                if "domain" not in ruleset["rules"][0]:
                                    ruleset["rules"][0]["domain"] = []
                                ruleset["rules"][0]["domain"].append(rule.Payload)
                            case "DomainSuffix":
                                if "domain_suffix" not in ruleset["rules"][0]:
                                    ruleset["rules"][0]["domain_suffix"] = []
                                ruleset["rules"][0]["domain_suffix"].append(f".{rule.Payload}")
                            case "IPCIDR":
                                if "ip_cidr" not in ruleset["rules"][0]:
                                    ruleset["rules"][0]["ip_cidr"] = []
                                ruleset["rules"][0]["ip_cidr"].append(rule.Payload)
                    dist.write(json.dumps(ruleset, indent=2))
                case _:
                    raise TypeError(f'Unsupported rule type "{src.Type}". File: {dst}.')
        case _:
            raise TypeError("Target type unsupported, "
                            "only accept 'text', 'text-plus', 'yaml', 'surge-compatible' or 'clash-compatible'."
                            )


def batch_dump(src: RuleSet, targets: list, dst_path: Path, filename: str) -> None:
    for target in targets:
        dump(src, target, dst_path/target, filename)


def apply_patch(src: RuleSet, name: str, override_patch_loc: Path = Path("")) -> RuleSet:
    try:
        if override_patch_loc != Path(""):
            patch = open(override_patch_loc/(name + ".txt"), mode="r").read().splitlines()
        else:
            patch = open(const.PATH_SOURCE_PATCH/(name + ".txt"), mode="r").read().splitlines()
    except FileNotFoundError:
        logging.warning(f'Patch "{name + ".txt"}" not found.')
        return src
    logging.info(f'Start applying patch "{name + ".txt"}"')
    for line in patch:
        if line.startswith("#"):
            continue
        parsed_line = line.split(":")
        if parsed_line[0] == "ADD":
            if parsed_line[1].startswith("."):
                rule = Rule("DomainSuffix", parsed_line[1].strip("."))
            else:
                rule = Rule("DomainFull", parsed_line[1])
            if rule not in src:
                src.add(rule)
                logging.debug(f'Rule "{rule}" added.')
            else:
                logging.warning(f"Already exist: {rule}")
        elif parsed_line[0] == "REM":
            if parsed_line[1].startswith("."):
                rule = Rule("DomainSuffix", parsed_line[1].strip("."))
            else:
                rule = Rule("DomainFull", parsed_line[1])
            if rule in src:
                src.remove(rule)
                logging.debug(f'Rule "{rule}" Removed.')
            else:
                logging.warning(f"Not found: {rule}")
    logging.info(f'Patch "{name + ".txt"}" applied.')
    return src
