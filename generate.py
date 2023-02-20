import re
from requests import get
from abp.filters import parse_filterlist
domain_list_base = './domain-list-community/data/'

def import_processor(src, exclusion=None):
    import_regex = re.compile('^include\:(\S*)$')
    content = []
    for line in src:
        import_flag = import_regex.match(line)
        if import_flag and import_flag.group(1) != exclusion:
            import_file = open(domain_list_base + import_flag.group(1), mode='r').read().splitlines()
            content += import_processor(import_file)
            continue
        content.append(line)
    return content

def convert(src, target):
    # The following 2 regexes' group 1 matches domains without "@cn" directive.
    regex_fulldomain = re.compile('^full\:(\S*)(?: @cn)?$')
    regex_subdomain = re.compile('^([a-zA-Z0-9-]*(?:\.\S*)?)(?: @cn)?$')
    regex_invaild = re.compile('^(?:regexp\:|keyword\:).*$')
    list = []
    for line in src:
        fulldomain = regex_fulldomain.match(line)
        subdomain = regex_subdomain.match(line)
        invaild = regex_invaild.match(line)
        if target == 'surge' or target == 'plain':
            if fulldomain:
                list.append(fulldomain.group(1))
            elif subdomain and subdomain.group(1) != '':
                list.append('.' + subdomain.group(1))
            elif invaild:
                pass
        elif target == 'clash':
            if fulldomain:
                list.append("  - '" + fulldomain.group(1) + "'")
            elif subdomain and subdomain.group(1) != '':
                list.append("  - '+." + subdomain.group(1) + "'")
            elif invaild:
                pass
        else:
            raise TypeError("Target type unsupported, only accept 'surge', 'clash' or 'plain'.")
    if target == 'clash':
        list.sort()
        list.insert(0, "payload:")
    else:
        list.sort()
    return list

def batch_convert(targets, tools, exclusions=[]):
    for tool in tools:
        for target in targets:
            for exclusion in exclusions:
                o_file = open(domain_list_base + target, mode='r').read().splitlines()
                dist = open("./dists/" + tool + "/" + target + ".txt", mode='w')
                o_content = import_processor(o_file, exclusion)
                for line in convert(o_content, tool):
                    dist.writelines(line + '\n')
                dist.close()

# Stage 1: Sync advertisements blocking and privacy protection rules.
regex_ip = re.compile('((2(5[0-5]|[0-4]\d))|[0-1]?\d{1,2})(\.((2(5[0-5]|[0-4]\d))|[0-1]?\d{1,2})){3}') ## IP addresses shouldn't be added.
## AdGuard Base Filter
url_base = 'https://raw.githubusercontent.com/AdguardTeam/AdguardFilters/master/BaseFilter/sections/adservers.txt'
## Easylist China
url_cn = 'https://easylist-downloads.adblockplus.org/easylistchina.txt'
## もちフィルタ
url_jp = 'https://raw.githubusercontent.com/eEIi0A5L/adblock_filter/master/mochi_filter.txt'
## AdGuard Mobile Filter
url_mobile = 'https://raw.githubusercontent.com/AdguardTeam/AdguardFilters/master/MobileFilter/sections/adservers.txt'
## ADgk
url_cn_extend = 'https://raw.githubusercontent.com/banbendalao/ADgk/master/ADgk.txt'
dist_surge = open('./dists/surge/protection.txt', mode='w')
dist_clash = open('./dists/clash/protection.txt', mode='w')
dist_clash.writelines("payload:\n")

content = (
    get(url_base).text +
    get(url_cn).text +
    get(url_jp).text +
    get(url_mobile).text +
    get(url_cn_extend).text
    ).splitlines()

list_block = []
list_exceptions = []

for line in parse_filterlist(content):
    if (line.type == 'filter'
    and line.action == 'block'
    and line.selector['type'] == 'url-pattern'
    and line.text.find('/') == -1
    and line.text.find('*') == -1
    and line.text.find('=') == -1
    and line.text.find('~') == -1
    and line.text.find('?') == -1
    and line.text.find('#') == -1
    and line.text.find(',') == -1
    and not line.text.find('.') == -1
    and not regex_ip.search(line.text)
    and not line.text.startswith('_')
    and not line.text.startswith('-')
    and not line.text.startswith('^')
    and not line.text.startswith('[')
    and not line.text.endswith('.')
    and not line.text.endswith('_')
    and not line.text.endswith('|')
    and not line.text.endswith(']')
    and not line.text.endswith(';')
    and not line.options):
        if line.text.startswith('.'):
            list_block.append(line.text.replace('^', ''))
        else:
            list_block.append(line.text.replace("||", '.').replace('^', ''))
    if (line.type == 'filter'
    and line.action == 'allow'
    and line.selector['type'] == 'url-pattern'
    and line.text.find('/') == -1
    and line.text.find('*') == -1
    and line.text.find('=') == -1
    and line.text.find('~') == -1
    and line.text.find('?') == -1
    and line.text.find('#') == -1
    and line.text.find(',') == -1
    and not line.text.find('.') == -1
    and not re.search(regex_ip, line.text)
    and not line.text.startswith('_')
    and not line.text.startswith('-')
    and not line.text.startswith('^')
    and not line.text.startswith('[')
    and not line.text.endswith('.')
    and not line.text.endswith('_')
    and not line.text.endswith('|')
    and not line.text.endswith(']')
    and not line.text.endswith(';')
    and not line.options):
        list_exceptions.append(line.text)

v2fly_ads = open(domain_list_base + "category-ads-all", mode='r')
list_block += convert(import_processor(v2fly_ads), "plain")
list_block = list(set(list_block))
list_block.sort()

for domain in list_block:
    dist_surge.writelines(domain + '\n')
    if domain.startswith('.'):
        dist_clash.writelines("  - '+" + domain + "'\n")
    else:
        dist_clash.writelines("  - '" + domain + "'\n")

dist_surge.close()
dist_clash.close()
# Stage 1 finished.

# Stage 2: Sync exceptions with AdGuard.
url_exceptions_1 = 'https://raw.githubusercontent.com/AdguardTeam/AdGuardSDNSFilter/master/Filters/exceptions.txt'
url_exceptions_2 = 'https://raw.githubusercontent.com/AdguardTeam/AdGuardSDNSFilter/master/Filters/exclusions.txt'
dist_surge = open('./dists/surge/exceptions.txt', mode='w')
dist_clash = open('./dists/clash/exceptions.txt', mode='w')
content_exceptions = (get(url_exceptions_1).text + get(url_exceptions_2).text).splitlines() + list_exceptions
list_exceptions = []
for line in parse_filterlist(content_exceptions):
    if (line.type == 'filter'
    and line.selector['type'] == 'url-pattern'
    and line.text.find('/') == -1
    and line.text.find('*') == -1
    and line.text.find('=') == -1
    and line.text.find('~') == -1
    and line.text.find('?') == -1
    and line.text.find('#') == -1
    and line.text.find(',') == -1
    and not line.text.find('.') == -1
    and not re.search(regex_ip, line.text)
    and not line.text.startswith('_')
    and not line.text.startswith('-')
    and not line.text.startswith('^')
    and not line.text.startswith('[')
    and not line.text.endswith('.')
    and not line.text.endswith('_')
    and not line.text.endswith(']')
    and not line.text.endswith(';')
    and not line.options):
        domain = line.text.replace('@','').replace('^','').replace('|','')
        if not domain.startswith('-'):
            list_exceptions.append(domain)

list_exceptions = list(set(list_exceptions))
list_exceptions.sort()

dist_clash.writelines("payload:\n")

for line in list_exceptions:
    dist_surge.writelines("." + line + '\n')
    dist_clash.writelines("  - '+." + line + "'\n")
dist_surge.close()
dist_clash.close()
# Stage 2 finished.

# Stage 3: Sync Bahamut, CN, DMM, Google FCM, Microsoft, niconico, PayPal and YouTube domains with v2fly community.
to_convert = ['bahamut', 'geolocation-cn', 'dmm', 'googlefcm', 'microsoft', 'niconico', 'paypal', 'youtube']
exclusion = ['github'] ## GitHub's domains are included in "microsoft", but its connectivity mostly isn't as high as Microsoft.
batch_convert(to_convert, ['surge', 'clash'], exclusion)
# Stage 3 finished.

# Stage 4: Remove CN domains with Chinese TLDs.
cntld = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/tld-cn"
regex_cntld = re.compile('^([a-zA-Z0-9-]*(?:\.\S*)?)( #.*)?$')

list_cntld = []
for line in open(domain_list_base + "tld-cn", mode='r').read().splitlines():
    istld = regex_cntld.match(line)
    if istld and istld[1] != '':
        list_cntld.append('.' + istld[1])
dist_surge = open('./dists/surge/geolocation-cn.txt', mode='r')
dist_clash = open('./dists/clash/geolocation-cn.txt', mode='r')
list_domain_surge = dist_surge.read().splitlines()
list_domain_clash = dist_clash.read().splitlines()
## After loading temporary rules, reopen rule files as write mode.
dist_surge.close()
dist_surge = open('./dists/surge/geolocation-cn.txt', mode='w')
dist_clash.close()
dist_clash = open('./dists/clash/geolocation-cn.txt', mode='w')

for domain in list_domain_surge[:]:
    for tld in list_cntld:
        if domain.find(tld) != -1:
            list_domain_surge.remove(domain)
            break
for domain in list_domain_clash[:]:
    for tld in list_cntld:
        if domain.find(tld) != -1:
            list_domain_clash.remove(domain)
            break

for line in list_domain_surge:
    dist_surge.writelines(line + '\n')
for line in list_domain_clash:
    dist_clash.writelines(line + '\n')

dist_surge.close()
dist_clash.close()
## Stage 4 finished.