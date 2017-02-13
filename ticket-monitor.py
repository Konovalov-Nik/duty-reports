import httplib
from time import sleep
from json import dumps
from ConfigParser import SafeConfigParser
from simple_salesforce import Salesforce

parser = SafeConfigParser()
parser.read('salesforce.conf')

sf_url = parser.get('SalesForce', 'url')
sf_usr = parser.get('SalesForce', 'username')
sf_pwd = parser.get('SalesForce', 'password')
sf_tkn = parser.get('SalesForce', 'token')
slack_hook = parser.get('Slack', 'monitor_hook_url')

sev_wait = [5, 20, 40, 80]

ntickets = {}

sf = Salesforce(custom_url=sf_url, username=sf_usr, password=sf_pwd, security_token=sf_tkn)


def slack_send(username, icon_emoji, text):
    params = dumps({"username": username,
                    "icon_emoji": icon_emoji,
                    "text": text
                    })
    conn = httplib.HTTPSConnection("hooks.slack.com")
    conn.request("POST", slack_hook, params)
    res = conn.getresponse()
    conn.close()
    return res.status, res.reason

while True:
    for t in ntickets:
        ntickets[t]['stillnew'] = False

    for case in sf.query("SELECT Id, Subject, Severity_Level__c, CaseNumber from Case where Status = 'New'")['records']:
        if case['Id'] in ntickets:
            nsev = int(case['Severity_Level__c'][-1])
            ntickets[case['Id']]['stillnew'] = True
            ntickets[case['Id']]['wait'] += 5
            if ntickets[case['Id']]['wait'] >= sev_wait[nsev-1]:
                print("A Sev %d ticket is still new (%d min since last notification), sending notification again (%s: %s)" %
                      (nsev, ntickets[case['Id']]['wait'], case['CaseNumber'], case['Subject']))

                slack_send("New Ticket Warning",
                           ":warning:",
                           "<!here> A %s ticket is still New! #%s <%s|%s>" %
                           (case['Severity_Level__c'], case['CaseNumber'], ntickets[case['Id']]['url'], ntickets[case['Id']]['title'])
                           )
                ntickets[case['Id']]['wait'] = 0
            else:
                print("Still new ticket, but too early to notify again (waited %d out of %d)... Sev %d, (%s: %s)" %
                      (ntickets[case['Id']]['wait'], sev_wait[nsev-1], nsev, case['CaseNumber'], case['Subject']))
        else:
            print("Found new ticket, recording and notifying (%s: %s)" % (case['CaseNumber'], case['Subject']))

            ntickets[case['Id']] = {'title': case['Subject'], 'url': sf_url + '/console#%2f' + case['Id'], 'wait': 0, 'stillnew': True}
            url = sf_url + '/console#%2f' + case['Id']

            slack_send("New Ticket Notification",
                       ":ticket:",
                       "A new %s ticket is here! #%s <%s|%s>" %
                       (case['Severity_Level__c'], case['CaseNumber'], ntickets[case['Id']]['url'], ntickets[case['Id']]['title'])
                       )

    to_del = []
    for t in ntickets:
        if not ntickets[t]['stillnew']:
            to_del.append(t)
    for t in to_del:
        del ntickets[t]
    del to_del

    print("Sleeping 5 minutes...")
    sleep(300)