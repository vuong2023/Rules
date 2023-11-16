import logging.config
from pathlib import Path
from time import time_ns

from abp.filters.parser import parse_filterlist
from aggregate6 import aggregate
from requests import Session

from Utils import const, geosite, rule

logging.config.fileConfig("logging.ini")
logger = logging.getLogger("root")

# Generate reject and exclude rules.
logger.info("Start generating reject and exclude rules.")
START_TIME = time_ns()
connection = Session()

src_rejections = []
for url in const.LIST_REJECT_URL:
    src_rejections += (connection.get(url).text.splitlines())

logger.info(f"Imported {len(src_rejections)} lines of reject rules from defined sources.")

src_exclusions = []
for url in const.LIST_EXCL_URL:
    src_exclusions += connection.get(url).text.splitlines()

logger.info(f"Imported {len(src_exclusions)} lines of exclude rules from defined sources.")

ruleset_rejections = rule.RuleSet("Domain", [])
ruleset_exclusions_raw = rule.RuleSet("Domain", [])

for line in parse_filterlist(src_rejections):
    if (not line.type == "filter"
            or line.options
            or line.text.startswith("^")
            or not line.selector["type"] == "url-pattern"):
        continue
    line_stripped = line.text.strip("@").strip("|").strip("^")
    if rule.is_domain(line_stripped):
        if line.action == "block":
            if line.text.startswith("."):
                rule_reject = rule.Rule("DomainSuffix", line.text.strip(".").strip("^"))
                ruleset_rejections.add(rule_reject)
                logger.debug(f'Line "{line.text}" is added to reject set. {rule_reject}.')
            else:
                rule_reject = rule.Rule("DomainSuffix", line.text.strip("|").strip("^"))
                ruleset_rejections.add(rule_reject)
                logger.debug(
                    f'Line "{line.text}" is added to reject set. "{rule_reject}".'
                )
        elif line.action == "allow":
            src_exclusions.append(line.text)
            logger.debug(f'Line "{line.text}" is added to exclude set.')

for line in parse_filterlist(src_exclusions):
    if (not line.type == "filter"
            or line.options
            or line.text.startswith("^")
            or not line.selector["type"] == "url-pattern"):
        continue
    line_stripped = line.text.strip("@").strip("|").strip("^")
    if rule.is_domain(line_stripped):
        rule_exclude = rule.Rule("DomainFull", line_stripped)
        ruleset_exclusions_raw.add(rule_exclude)
        logger.debug(f'Line "{line.text}" is added to raw exclude set. "{rule_exclude}".')

src_rejections_v2fly = set(
    open(const.PATH_SOURCE_V2FLY/"category-ads-all", mode="r", encoding="utf-8").read().splitlines())
ruleset_rejections_v2fly = geosite.parse(src_rejections_v2fly)
ruleset_rejections |= ruleset_rejections_v2fly
logger.info(f"Imported {(len(ruleset_rejections_v2fly))} reject rules from v2fly category-ads-all list.")

ruleset_exclusions = rule.RuleSet("Domain", [])
logger.debug("Start deduplicating reject and exclude set.")
ruleset_rejections.dedup()
for domain_exclude in ruleset_exclusions_raw.deepcopy():
    for domain_reject in ruleset_rejections.deepcopy():
        if (domain_reject.Payload == domain_exclude.Payload and domain_reject.Type == domain_exclude.Type) \
                or (domain_reject.Payload == domain_exclude.Payload and
                    domain_reject.Type == "DomainFull" and domain_exclude.Type == "DomainSuffix"):
            ruleset_rejections.remove(domain_reject)
            ruleset_exclusions_raw.remove(domain_exclude)
            logger.debug(f"{domain_reject} is removed as excluded by {domain_exclude}.")

for domain_exclude in ruleset_exclusions_raw:
    for domain_reject in ruleset_rejections:
        if domain_exclude.Payload.endswith(domain_reject.Payload):
            ruleset_exclusions.add(domain_exclude)
            logger.debug(f"{domain_exclude} is added to final exclude set.")

ruleset_rejections = rule.apply_patch(ruleset_rejections, "reject")
ruleset_exclusions = rule.apply_patch(ruleset_exclusions, "exclude")

logger.info(f"Generated {len(ruleset_rejections)} reject rules.")
logger.info(f"Generated {len(ruleset_exclusions)} exclude rules.")
rule.batch_dump(ruleset_rejections, const.TARGETS, const.PATH_DIST, "reject")
rule.batch_dump(ruleset_exclusions, const.TARGETS, const.PATH_DIST, "exclude")

END_TIME = time_ns()
logger.info(f"Finished. Total time: {format((END_TIME - START_TIME) / 1e9, '.3f')}s\n")

# Generate domestic rules.
logger.info("Start generating domestic rules.")
START_TIME = time_ns()

src_domestic = set(open(const.PATH_SOURCE_V2FLY/"geolocation-cn", mode="r", encoding="utf-8").read().splitlines())
ruleset_domestic = geosite.parse(src_domestic, None, ["!cn"])
logger.info(f"Imported {len(ruleset_domestic)} domestic rules from v2fly geolocation-cn list.")

for item in ruleset_domestic.deepcopy():
    tld_overseas = (".hk", ".kr", ".my", ".sg", ".au", ".tw", ".in", ".ru", ".us", ".fr", ".th", ".id", ".jp")
    if any([item.Payload.endswith(os_tld) for os_tld in tld_overseas]):
        ruleset_domestic.remove(item)
        logger.debug(f"{item} removed for having a overseas TLD.")
ruleset_domestic = rule.apply_patch(ruleset_domestic, "domestic")
ruleset_domestic.dedup()

# Surge ignores eTLDs in the domain set. So it needs a not-optimised version.
rule.batch_dump(ruleset_domestic, ["text"], const.PATH_DIST, "domestic_withcntld")

# Add all domestic TLDs to domestic rules, then perform deduplication.
src_domestic_tlds = set(open(const.PATH_SOURCE_V2FLY/"tld-cn", mode="r", encoding="utf-8").read().splitlines())
ruleset_domestic_tlds = geosite.parse(src_domestic_tlds)
logger.info(f"Imported {len(ruleset_domestic_tlds)} domestic TLDs.")
ruleset_domestic |= ruleset_domestic_tlds
ruleset_domestic.dedup()
logger.info(f"Generated {len(ruleset_domestic)} domestic rules.")
rule.batch_dump(ruleset_domestic, const.TARGETS, const.PATH_DIST, "domestic")

END_TIME = time_ns()
logger.info(f"Finished. Total time: {format((END_TIME - START_TIME) / 1e9, '.3f')}s\n")

# Convert domestic CIDR rules.
logger.info("Start converting domestic CIDR rules.")
START_TIME = time_ns()
src_cidr = connection.get(const.URL_CHNROUTES2).text.splitlines()
ruleset_cidr = rule.RuleSet("IPCIDR", [])
for line in src_cidr:
    if not line.startswith("#"):
        ruleset_cidr.add(rule.Rule("IPCIDR", line))
logger.info(f"Generated {len(ruleset_cidr)} domestic IPv4 rules.")

rule.batch_dump(ruleset_cidr, const.TARGETS, const.PATH_DIST, "domestic_ip")

src_cidr6 = connection.get(const.URL_CHNROUTES_V6).text.splitlines()
list_cidr6_raw = []
for line in src_cidr6:
    if "apnic|CN|ipv6" in line:
        parts = line.split("|")
        list_cidr6_raw.append(f"{parts[3]}/{parts[4]}")
list_cidr6_raw = aggregate(list_cidr6_raw)
ruleset_cidr6 = rule.RuleSet("IPCIDR", [])
for cidr in list_cidr6_raw:
    ruleset_cidr6.add(rule.Rule("IPCIDR6", cidr))
logger.info(f"Generated {len(ruleset_cidr6)} domestic IPv6 rules.")

rule.batch_dump(ruleset_cidr6, const.TARGETS, const.PATH_DIST, "domestic_ip6")

END_TIME = time_ns()
logger.info(f"Finished. Total time: {format((END_TIME - START_TIME) / 1e9, '.3f')}s\n")

# Convert v2fly community rules.
logger.info("Start converting v2fly community rules.")
START_TIME = time_ns()

CATEGORIES = [
    "bahamut",
    "bing",
    "dmm",
    "googlefcm",
    "microsoft",
    "niconico",
    "openai",
    "paypal",
    "youtube",
]
EXCLUSIONS = [
    "github",  # GitHub's domains are included in "microsoft", but its connectivity mostly isn't as high as Microsoft.
    "bing",  # Bing has a more restricted ver for Mainland China.
]
geosite.batch_convert(CATEGORIES, const.TARGETS, EXCLUSIONS)

END_TIME = time_ns()
logger.info(f"Finished. Total time: {format((END_TIME - START_TIME) / 1e9, '.3f')}s\n")

# Generate custom rules.
logger.info("Start generating custom rules.")
START_TIME = time_ns()
list_file_custom = Path.iterdir(const.PATH_SOURCE_CUSTOM)
for filename in list_file_custom:
    if filename.is_file():
        logger.debug(f'Start converting "{filename.name}".')
        ruleset_custom = rule.custom_convert(filename)
        rule.batch_dump(ruleset_custom, const.TARGETS, const.PATH_DIST, filename.stem)
        logger.debug(f"Converted {len(ruleset_custom)} rules.")

# There's no personal classical type ruleset. So no logic about that.
list_file_personal = Path.iterdir(const.PATH_SOURCE_CUSTOM/"personal")
for filename in list_file_personal:
    logger.debug(f'Start converting "{filename.name}".')
    ruleset_personal = rule.custom_convert(filename)
    rule.batch_dump(ruleset_personal, ["text", "text-plus", "yaml", "surge-compatible", "clash-compatible"],
                    const.PATH_DIST/"personal", filename.stem)
    rule.dump(ruleset_personal, "geosite", const.PATH_DIST/"geosite", ("personal-" + filename.stem))
    logger.debug(f"Converted {len(ruleset_personal)} rules.")

END_TIME = time_ns()
logger.info(f"Finished. Total time: {format((END_TIME - START_TIME) / 1e9, '.3f')}s\n")
