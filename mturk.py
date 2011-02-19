#!/usr/bin/python
"""
  Updated for Projrand_5 (5c/10c, w/ coin-flipper)
"""
testMode = True

#set-up
from boto.mturk.connection import *
from boto.mturk.question import *
from boto.mturk.price import *
from boto.mturk.qualification import *
from boto.s3 import *
from os.path import *
import sys,getopt,re,cPickle,urllib,string,time,os,uuid,mimetypes,codecs
from pprint import pprint
bucketname = 'amk.com.voxilate.mturk'
if testMode:
  print 'in testmode'
  conn = MTurkConnection(host='mechanicalturk.sandbox.amazonaws.com')
else:
  print 'real life'
  conn = MTurkConnection()

def post_html_question(title, description, quals, num_times, price, q_url, keywords=[]):
  """ creates a new html question in mechanical turk.  Saves you from
having to write your own ExternalQuestion wrapper, but for quals you're
still on your own, sorry
  
returns resulting HITId"""
  question = ExternalQuestion(q_url, 275)#frame_height, arbitrary
  result = conn.create_hit(
    question=question,
    title=title,
    description=description,
    keywords=keywords,
    reward=Price(float(price)),
    max_assignments=num_times,
    duration=120,
    qualifications=quals
  )
  return result[0].HITId or -1#resulting hit ID or broken

#note: after page_size > 100, we'll actually need to paginate. What a bitch.
def get_answers(hit_id):
  """returns a list of tuples (answer, worker_id, assignment_id)"""
  assignments = conn.get_assignments(hit_id=hit_id, page_size=100)
  return [(assign.answers[0],
      	   assign.WorkerId,
           assign.AssignmentId) for assign in assignments]

def accept_and_pay(worker_id, assign_id, bonus_price=0.00, 
	   reason="Congratulations!"):
  try:
    result = conn.approve_assignment(assign_id)
  except BaseException:
    print "looks like this one was already paid for. or, any other error" 
    return False# no bonus if already paid for
  # todo here: prevent duplicates (IE, make sure assignment 
  # had not already been approved
  if bonus_price > 0:
    conn.grant_bonus(worker_id, assign_id, Price(amount=bonus_price), reason)
  return True

def reject(assign_id, reason="That was not correct"):
  try:
    conn.reject_assignment(assign_id, reason)
    return True
  except BaseException:
    print "looks like this one was already rejected. or, any other error" 
    return False

def buildQuals(accept_max=None, accept_min=None, max_done=None, min_done=None):
  qualifications = None#for some reason, this isn't being cleared
  qualifications = Qualifications()
  if accept_max is not None: 
    q = PercentAssignmentsApprovedRequirement('LessThanOrEqualTo', accept_max)
    q.required_to_preview = True
    qualifications.add(q)
  if accept_min is not None:
    q = PercentAssignmentsApprovedRequirement('GreaterThanOrEqualTo', accept_min)
    q.required_to_preview = True
    qualifications.add(q)
  if max_done is not None:
    q = NumberHitsApprovedRequirement('LessThanOrEqualTo', max_done)
    q.required_to_preview = True
    qualifications.add(q)
  if min_done is not None:
    q = NumberHitsApprovedRequirement('GreaterThanOrEqualTo', min_done)
    q.required_to_preview = True
    qualifications.add(q)
  return qualifications

#test code
def create_ht_hits(base_price=0.05, heads='10c', tails='5c', flip_but='false'):
  """base price is a double (ie, 0.05)
     heads, tails are strings ie, 10c, 5c"""
  range_cutoffs = [(None, 100),(99, 98),(97, 95),(94, 90),(89, None)]
  #range_cutoffs = [(None, 100),(97, 95)]
  tasks_cutoff = 20

  q_url = "http://www.pennapps.com/mturk/flipacoin_generic.php?heads=%s&amp;tails=%s&amp;flipGen=%s&amp;real=" % (heads, tails, flip_but) + ('false' if testMode else 'true')  
  desc = "Project Random is running a one-question quiz. \n\nNote: You may only participate in one ProjectRandom experiment."
  title = "One quick question. Should take ~15 seconds."
  result_hits = []
  def projectrandom_q(quals):
    return post_html_question(title, desc, quals, 
      num_times=50, price=base_price, q_url=q_url, keywords=["survey", "test", "easy", ])
  #experienced cutoffs
  for cutoff in range_cutoffs:
    result_hits.append((cutoff, projectrandom_q(
      buildQuals(cutoff[0], cutoff[1], None, tasks_cutoff))))
  #newbie cutoff
  result_hits.append(((None, None), projectrandom_q(
    buildQuals(None, None, tasks_cutoff - 1, None))))
  return result_hits

def print_csv(hit_list):
  results = []#arr of hit_group_name : (hit_id, #heads, #tails)
  for hit in hit_list:
    hit_results = get_answers(hit[1])
    num_blanks = len(filter((lambda x: not has_result(x)), hit_results))
    hit_results = filter(has_result, hit_results)
    num_heads = len(filter(is_head, hit_results))
    num_cheaters = len(filter(cheated, hit_results))
    num_cheatersfp = len(filter(cheated_for_profit, hit_results))
    num_tails = len(hit_results) - num_heads
    results.append((hit[0], hit[1], num_heads, num_tails, 
                    num_cheaters, num_cheatersfp, num_blanks))

  csv = "Name\tHit ID\t#Heads\t#Tails\t#Cheaters\t#Cheaters(for profit)"+\
      "\t#Blank Results\t%Heads\t#Participants\n"
  def to_csv(content): return str(content) + "\t"
  for hit in results:
    for entry in hit: csv += to_csv(entry)
    total = hit[2] + hit[3]
    csv += to_csv(100.0 * hit[2] / total)
    csv += to_csv(total)
    csv += "\n"
  print csv
def cheated_for_profit(answer):
  return is_head(answer) and not is_head(answer, u'flip_true')
def cheated(answer):
  return is_head(answer) != is_head(answer, u'flip_true')
def has_result(answer): # some edge-cases don't have results.
  return any(map(lambda ans: ans.QuestionIdentifier == u'result', answer[0]))
def is_head(answer, ident=u'result'): 
  # with multiple rows, check all parts of answer
  right_part = filter(lambda ans: ans.QuestionIdentifier == ident, 
                answer[0])
  if len(right_part) != 1:
     print "ERROR, WEIRD ANSWER!", answer
     for part in answer[0]:
       print part.QuestionIdentifier + ": " + part.FreeText
  return len(right_part) > 0 and right_part[0].FreeText == u'heads'
  #the one below worked until we have multiple possible heads
  #return any(map(lambda ans: ans.FreeText == u'heads', answer[0]))

#project random 1
hit_list = [("100%", u'1NDCZYKKHE0PJNCX38JN8DTG8KACRG'),
            ("98-99%", u'1HAP633YC83RR30ZYB26GFMFT755IX'),
            ("97/95%", u'1N97AIQ2ZZ01K2CAIXJSYNYCUMTCS4'),
            ("94-90%", u'11RRTAQZP9M7ILR60NFOV5EW3GS9XS'),
            ("<90%", u'1OV175GB5BN5PJJFP2D7UKK9ZA3FM6'),
            ("<20 Hits", u'13WZ947TADA2V76594ZT1WXIHB0P8U')]

#project random 2
#5c/10c
hit_list2 = [('100%', u'11AS9XI8SHRYVT1MZZ7NNW1N6XS7PZ'), 
	     ('98-99%', u'17OS5STSYZ9JV521ZCMCN1RXBTE7QQ'), 
	     ('97-95%', u'16QPTY5534VQNAKMEAQ0G6UT2VXLA6'), 
	     ('94-90%', u'13B68VH8U8QA3OS0OA0GN6IJ509Y3F'),
       ('<90%', u'10ZS3NWEBR24K8ZKMK5JWEVEJGTVJF'), 
	     ('<20 Hits', u'1E4BDSOKPRYZVS52455VXTVRY5TVKE')]
hit_list2.reverse()#in place
#10c/15c
hit_list3 = [('97-95%', u'1RT6LH7Q5FLRJSIPUG4GJSC06ZXYLH'),
             ('100%', u'1K6HBZZ2IHIZ7Q2LSJK3MVWAAMK805'),
            ]
#3c/8c
hit_list4 = [('97-95%', u'1XO7N3IELR2D1B5GDK51R7PKZGLKD1'),
             ('100%', u'1FK4O8V51O4PTGOBWA0VGZWD6SXX1D'),
            ]
#5c/10c w/ generator
hit_list5 = [
 ('100%', u'1562QNH137YXAW2OVS1A5SEIXFHAAX'),
 ('99-98%', u'1F84T4IXYPLW6J5QN89T4TJFG10SFN'),
 ('97-95%', u'1EZ0TQKF5LUFYTBUEHWKOM6WMOAPJ7'),
 ('94-90%', u'19UMGJ5XPBOZEYK2PYHKNA4ILDUMMC'),
 ('<90%', u'1BR8TING8UD2KJ1LYSFBMEJRHG0SGM'),
 ('<20 Hits', u'1SOBPNA2BH8ZD5JL4N7EVC0R0HCZM6')]
hit_list5.reverse()

#this code pays everybody run it once.
def pay_for_random(h_list):
  print "Not paying, in case this is an accident. remove then next line to pay"
  return False
  
  for hit in h_list:
    for answer in get_answers(hit[1]):
      if has_result(answer):
        bonus_size = 0.05 if is_head(answer) else 0.00
        if accept_and_pay(answer[1], answer[2], bonus_size):
          print "paid: %s (+%f)" % (answer[1], bonus_size)
      else:
        if reject(answer[2], "You didn't pick heads or tails."):
          print "rejected: %s" % (answer[1],)

def worker_list(hits):
  l = set()
  for hit in hits:
    for answer in get_answers(hit[1]):
      l.add(answer[1])
  return l

#THIS CODE EXECUTES:
#print create_ht_hits(.05, '10c', '5c', True)
#print_csv(hit_list5)
#pay_for_random(hit_list5)

##rock paper scissors specific code
#def decide_winners(answers):
#  """input: list of tuples (answer, worker_id, assign_id)
#  returns list of tuples in the form of ('w'/'t'/'l', worker, assign)"""
#  # zip em together and pair people up
#  pairs = [pair for pair in zip(answers[::2], answers[1::2])]
#  results = reduce((lambda x,y: x+y),[get_winner(pair) for pair in pairs])
#  return results
#def get_winner(pair):
#  """takes a tuple, each member of which 
#  is a tuple (answer, worker_id, assign_id), returns an array of list 2
#  in the right format"""
#  # Note: Rock = 1, Paper = 2, Scissors = 3
#  if pair[0][0] == pair[1][0]: results = ('t', 't')
#  elif int(pair[0][0]) - int(pair[1][0]) in [1, -2]: results = ('w', 'l')
#  else: results = ('l', 'w')
#  
#  return [(results[0], pair[0][1], pair[0][2]),
#          (results[1], pair[1][1], pair[1][2])] 
#
#results = decide_winners(ans)
#bonus = {'w':.04, 't':.02, 'l':0}
#reason = {'w':"You won!", 't':"You tied.", 'l':0}
#def pay():
#  for result in results:
#    accept_and_pay(result[1], result[2], bonus[result[0]], reason[result[0]])
