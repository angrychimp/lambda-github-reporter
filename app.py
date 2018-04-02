"""
  ==  Generates a status report ==

  Should run each Monday. Will create a report based on status from 1 week ago

"""

from datetime import datetime, timedelta
from base64 import b64decode
from smtplib import SMTP
import requests
import os
import sys
import random
import json
import boto3
from jinja2 import Environment, Template

SMTP_USER = os.environ['SMTP_USER'] if 'SMTP_USER' in os.environ else ""
SMTP_PASS_ENCRYPTED = os.environ['SMTP_PASS'] if 'SMTP_PASS' in os.environ else ""
SMTP_ENDPOINT = os.environ['SMTP_ENDPOINT'] if 'SMTP_ENDPOINT' in os.environ else ""
SMTP_PORT = int(os.environ['SMTP_PORT']) if 'SMTP_PORT' in os.environ else 25

TO_ADDR_LIST = os.environ['TO_ADDR_LIST'] if 'TO_ADDR_LIST' in os.environ else ""
CC_ADDR_LIST = os.environ['CC_ADDR_LIST'] if 'CC_ADDR_LIST' in os.environ else ""
FROM_ADDR = os.environ['FROM_ADDR'] if 'FROM_ADDR' in os.environ else ""

GITHUB_API_URL = os.environ['GITHUB_API_URL'] if 'GITHUB_API_URL' in os.environ else "https://api.github.com/repos"
GITHUB_API_TOKEN_ENCRYPTED = os.environ['GITHUB_API_TOKEN'] if 'GITHUB_API_TOKEN' in os.environ else ""
GITHUB_REPO_PREFIX = os.environ['GITHUB_REPO_PREFIX'] if 'GITHUB_REPO_PREFIX' in os.environ else ""

# Decode the password and token
SMTP_PASS = boto3.client('kms').decrypt(CiphertextBlob=b64decode(SMTP_PASS_ENCRYPTED))['Plaintext'].decode("utf-8") 
GITHUB_API_TOKEN = boto3.client('kms').decrypt(CiphertextBlob=b64decode(GITHUB_API_TOKEN_ENCRYPTED))['Plaintext'].decode("utf-8") 

def contrasting_text_color(hex_str):
    (r, g, b) = (hex_str[:2], hex_str[2:4], hex_str[4:])
    return '000' if 1 - (int(r, 16) * 0.299 + int(g, 16) * 0.587 + int(b, 16) * 0.114) / 255 < 0.5 else 'fff'

def get_data(**kwargs):
    qtype = kwargs['Type'] if 'Type' in kwargs else "issues"
    repo = kwargs['Repo'] if 'Repo' in kwargs else ""
    query = {"per_page": 100, "page": 1}

    repo = '/'.join([GITHUB_REPO_PREFIX, repo]) if len(GITHUB_REPO_PREFIX) else repo
    
    if 'State' in kwargs:
        query["state"] = kwargs['State']
    if 'Assignee' in kwargs:
        if kwargs['Assignee'] is False:
            query["no"] = "assignee"
        else:
            query["assignee"] = kwargs['Assignee']
    if 'Since' in kwargs:
        # Type "pulls" does not support "since", so ignore and handle in loop
        if qtype != "pulls":
            query["since"] = kwargs['Since'].strftime('%Y-%m-%dT%H:%M:%S+00:00')
    if 'Sort' in kwargs:
        query["sort"] = kwargs['Sort']
    if 'Direction' in kwargs:
        query["direction"] = kwargs['Direction']
    
    url = "%s/%s/%s" % (GITHUB_API_URL, repo, qtype)
    headers = {
        "Authorization": "token " + GITHUB_API_TOKEN,
        "Accept": "application/vnd.github.cerberus-preview"
    }
    more = True
    items = []
    while more:
        req = requests.get(url, headers=headers, params=query)
        batch = req.json()

        if type(batch) == dict:
            return batch
        
        # Type "pulls" does not support "since" so scan the batch
        if qtype == "pulls":
            # If we don't have "Since" defined, let's avoid a huge processing batch and just abort
            if 'Since' not in kwargs:
                items = batch
                more = False
            else:
                for item in batch:
                    if datetime.strptime(item['updated_at'], '%Y-%m-%dT%H:%M:%SZ') > kwargs['Since']:
                        items.append(item)
                    else:
                        more = False
                    
        else:
            items = [*items, *batch]
        if len(batch) < 100:
            more = False
        query["page"] = query["page"] + 1

    return items

def send_email(**kwargs):
    smtp = SMTP(host=SMTP_ENDPOINT, port=SMTP_PORT)
    if SMTP_PORT == 587:
        smtp.starttls()
    smtp.login(SMTP_USER, SMTP_PASS)
    smtp.set_debuglevel(0)
    response = smtp.sendmail(
        kwargs['From'],
        kwargs['To'],
        kwargs['Content'].encode('utf-8').strip()
    )
    smtp.quit()
    return '250 Ok' if response == {} else response

def handler(event, context):
    # Initialize the jinja env
    # Jinja environment
    env = Environment()
    env.filters['contrast'] = contrasting_text_color

    template = env.from_string(open('email.jinja').read())

    if 'Repos' not in event:
        # Only a single repo to evaluate
        repo_list = [event]
    else:
        repo_list = event['Repos']
    
    results = []
    for event in repo_list:
        start_time = datetime.utcnow() - timedelta(days=7)
        from_addr = event['From'] if 'From' in event else FROM_ADDR
        to_addr = event['To'] if 'To' in event else TO_ADDR_LIST
        cc_addr = event['Cc'] if 'Cc' in event else CC_ADDR_LIST

        to_list = to_addr.replace(' ', '').split(',') if len(to_addr) else []
        cc_list = cc_addr.replace(' ', '').split(',') if len(cc_addr) else []

        issues = get_data(Repo=event["Repo"], Type="issues", State="open", Assignee="*")
        assigned = []
        for issue in issues:
            if 'pull_request' not in issue:
                assigned.append(issue)
        
        issues = get_data(Repo=event['Repo'], Type="issues", State="open", Since=start_time, Sort="created")
        recent = []
        for issue in issues:
            if 'pull_request' not in issue:
                recent.append(issue)

        issues = get_data(Repo=event['Repo'], Type="issues", State="closed", Since=start_time, Sort="updated", Direction="desc")
        closed = []
        for issue in issues:
            if 'pull_request' not in issue:
                closed.append(issue)

        open_prs = get_data(Repo=event['Repo'], Type="pulls", State="open", Since=start_time, Sort="updated", Direction="desc")
        closed_prs = get_data(Repo=event['Repo'], Type="pulls", State="closed", Since=start_time, Sort="updated", Direction="desc")

        release = get_data(Repo=event['Repo'], Type="releases/latest")
        
        boundary = ''.join(random.choice('abcdef' + ''.join(str(i) for i in range(10))) for _ in range(28))
        mime_content = template.render(
            to_addr=to_list,
            cc_addr=cc_list,
            from_addr=from_addr,
            repo_name=event['Repo'],
            start_date=start_time.strftime('%a %b %d %Y'),
            report_date=datetime.now().strftime('%a %b %d %Y'),
            assigned=assigned,
            open_prs=open_prs,
            closed_prs=closed_prs,
            recent=recent,
            closed=closed,
            release=release,
            mime_boundary=boundary
        )
        
        # Send the email content
        rcpt = [*to_list, *cc_list]
        results.append({event['Repo']: send_email(Content=mime_content,From=from_addr,To=rcpt)})
    return json.dumps(results)

if __name__ == "__main__":
    event = json.loads(sys.argv[1])
    print(handler(event, {}))
