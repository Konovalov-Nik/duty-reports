import httplib2
from apiclient import discovery
from datetime import datetime, timedelta
from calendarapihelper import get_credentials
from engineers import engineers, ids, l2
from ConfigParser import SafeConfigParser
from simple_salesforce import Salesforce
from flask import Flask, request
import json
import time
from flask_apscheduler import APScheduler
import os
import xlrd

import logging
logging.basicConfig()

parser = SafeConfigParser()
parser.read('salesforce.conf')

sf_url = parser.get('SalesForce', 'url')
sf_usr = parser.get('SalesForce', 'username')
sf_pwd = parser.get('SalesForce', 'password')
sf_tkn = parser.get('SalesForce', 'token')

cal_id = parser.get('calendar', 'id')

credentials = get_credentials()
http = credentials.authorize(httplib2.Http())
service = discovery.build('calendar', 'v3', http=http)

class Config(object):
    JOBS = [
        {
            'id': 'job1',
            'func': 'duty-engineers:async_job',
            'trigger': 'interval',
            'seconds': 90
        }
    ]

    SCHEDULER_API_ENABLED = True

def async_job():
  sf = Salesforce(instance_url=sf_url,
                  username=sf_usr,
                  password=sf_pwd,
                  security_token=sf_tkn)

  now  = (datetime.utcnow()).isoformat()+'Z'
  then = (datetime.utcnow()+timedelta(minutes=1)).isoformat()+'Z'

  sheet = xlrd.open_workbook('l2.xlsx').sheet_by_index(2)

  eventsResult = service.events().list(
      calendarId=cal_id, timeMin=now, singleEvents = True,
      timeMax=then,orderBy='startTime',
      timeZone="UTC").execute()
  events = eventsResult.get('items', [])

  result = {}
  l1_crew = {}
  l2_crew = {}
  crew_keys = []
  on_duty_l2 = ''
  l2_unassigned = []
  l1_unassigned = []

  for event in events:
    if 'shift' in event['summary']:
      key = event['attendees'].pop()['email']
      if key not in crew_keys:
        crew_keys.append(key)

  for e in l2:
    e_day = datetime.now(l2[e]['tz']).strftime('%A')
    e_hour = int(datetime.now(l2[e]['tz']).strftime('%H'))

    if (e_day != 'Sunday' and e_day != 'Saturday'):
      if (e_hour >= 9) and (e_hour <= 17 ):
        l2_crew[e] = []
        for c in sf.query("SELECT Id, CaseNumber from Case where (OwnerId = '"+l2[e]['uid']+"') and status != 'Closed' and status != 'Solved' and status != 'Ignored' and status != 'Completed' and status != 'Converted'")['records']:
          l2_crew[e].append('<'+sf_url+'/console#%2f'+c['Id']+'|'+c['CaseNumber']+'>')

  for k in crew_keys:
    l1_crew[engineers[k]] = []
    for case in sf.query("SELECT Id, CaseNumber from Case where (OwnerId = '"+ids[k]+"') and status != 'Closed' and status != 'Solved' and status != 'Ignored' and status != 'Completed' and status != 'Converted'")['records']:
      l1_crew[engineers[k]].append('<'+sf_url+'/console#%2f'+case['Id']+'|'+case['CaseNumber']+'>')

  for case in sf.query("SELECT Id, CaseNumber from Case where OwnerId = '00GE0000003YOIEMA4' and status != 'Closed' and status != 'Solved' and status != 'Ignored' and status != 'Completed' and status != 'Converted'")['records']:
    l1_unassigned.append('<'+sf_url+'/console#%2f'+case['Id']+'|'+case['CaseNumber']+'>')

  for case in sf.query("SELECT Id, CaseNumber from Case where OwnerId = '00GE0000003YOIFMA4' and status != 'Closed' and status != 'Solved' and status != 'Ignored' and status != 'Completed' and status != 'Converted'")['records']:
    l2_unassigned.append('<'+sf_url+'/console#%2f'+case['Id']+'|'+case['CaseNumber']+'>')

  for i in xrange(sheet.nrows):
    if sheet.row_values(i)[5] == 'YES':
      on_duty_l2+= str(sheet.row_values(i)[2])

  result['timestamp'] = now
  result['l1'] = l1_crew
  result['l2'] = l2_crew
  result['od2'] = on_duty_l2
  result['l1u'] = l1_unassigned
  result['l2u'] = l2_unassigned
  os.environ['JSON_RESULT'] = str(json.dumps(result))

async_job()
print('app ready!')

if __name__ == '__main__':
  app = Flask(__name__)
  app.config.from_object(Config())
  scheduler = APScheduler()
  scheduler.init_app(app)
  scheduler.start()

  def gt(dt_str):
    dt, _, us= dt_str.partition(".")
    dt= datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S")
    us= int(us.rstrip("Z"), 10)
    return dt + timedelta(microseconds=us)

  def dict2message(d):
    message = ''
    for e in sorted(d, key=lambda e: len(d[e]), reverse=False):
      message +='*'+e+'*'+' : '+', '.join(d[e])+'  `'+str(len(d[e]))+'`'+str('\n')
    return message

  def process_l2(l2_stats, l2_on_duty):
    if l2_stats:
      extra = dict2message(l2_stats)
    elif l2_on_duty:
      extra = l2_on_duty+' is on duty. \n The remaining team will be available soon.'
    else:
      extra  = 'No engineers on-duty: L2 escalations team available only at 9:00-17:00 MSK/EEST/PDT'
    return extra

  @app.route('/json')
  def l1_handle():
    return str(json.dumps(json.loads(os.environ['JSON_RESULT'])['l1']))

  @app.route('/jsonl2')
  def l2_handle():
    return str(json.dumps(json.loads(os.environ['JSON_RESULT'])['l2']))

  @app.route('/', methods=['GET'])
  def summary():
    data = json.loads(os.environ['JSON_RESULT'])
    stamp = gt(data['timestamp'])

    #l1_on_duty =
    l2_on_duty = data['od2']

    l1_unpr = ', '.join(data['l1u'])
    l2_unpr = ', '.join(data['l2u'])

    p1 = 'Unassigned: '+l1_unpr+'\n' + dict2message(data['l1']) if l1_unpr else dict2message(data['l1'])
    p2 = 'Unassigned: '+l2_unpr+'\n' + process_l2(data['l2'], data['od2']) if l2_unpr else process_l2(data['l2'], data['od2'])

    if stamp < datetime.utcnow()-timedelta(minutes=5):
      return 'app cache outdated', 500

    r = {}
    r['response_type'] = 'in_channel'
    r['text'] = '`# L1: #`\n'+p1 + '`# L2: #`\n'+ p2

    return json.dumps(r), 200, {'Content-Type': 'application/json'}

  @app.route('/extra', methods=['GET'])
  def l2_stats():
    data = json.loads(os.environ['JSON_RESULT'])
    l2_stats = data['l2']
    l2_on_duty = data['od2']
    stamp = gt(data['timestamp'])
    prefix = ', '.join(data['l2u'])

    extra = process_l2(l2_stats, l2_on_duty)

    if stamp < datetime.utcnow()-timedelta(minutes=5):
      return 'app cache outdated', 500

    r = {}
    r['response_type'] = 'in_channel'
    r['text'] = 'Unassigned: '+prefix+'\n' + extra if prefix else extra

    return json.dumps(r), 200, {'Content-Type': 'application/json'}

  @app.route('/general', methods=['GET'])
  def l1_stats():

    data = json.loads(os.environ['JSON_RESULT'])
    l1_stats = data['l1']
    stamp = gt(data['timestamp'])
    prefix = ', '.join(data['l1u'])

    payload = dict2message(l1_stats)

    if stamp < datetime.utcnow()-timedelta(minutes=5):
      return 'app cache outdated', 500

    r = {}
    r['response_type'] = 'in_channel'
    r['text'] = 'Unassigned: '+prefix+'\n' + payload if prefix else payload

    return json.dumps(r), 200, {'Content-Type': 'application/json'}

  app.run(host='127.0.0.1', port=5002)
