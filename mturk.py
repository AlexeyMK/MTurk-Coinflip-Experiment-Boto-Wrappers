#!/usr/bin/python
"""Set of boto wrappers for running the MTurk coin-flip experiment 
   
   See: (http://alexeymk.com/flipping-coins-through-mechanical-turk-part-1).

   To set up boto, make sure to add a ~/.boto file with your MTurk details:
   (http://code.google.com/p/boto/wiki/BotoConfig)

   To replicate the experiment, a matching php file (flipacoin_generic.php)
   would also be required. Alas, that is more code that should also probably
   get cleaned up before it sees the light of day.
"""
#TODO: be more specific with imports
from boto.mturk.connection import *
from boto.mturk.question import *
from boto.mturk.price import *
from boto.mturk.qualification import *
from boto.s3 import *
from os.path import *
import urllib
import sys,os

TEST_MODE = True
SAFETY_BREAK = True
HTML_FRAME_HEIGHT = 275 #arbitrary and depends on question HTML itself
EXTERNAL_Q_URL = "http://ve.rckr5ngx.vesrv.com/mturk/flipacoin_generic.php"
BONUS_SIZE = 0.05

if TEST_MODE:
  print 'in testmode'
  conn = MTurkConnection(host='mechanicalturk.sandbox.amazonaws.com')
else:
  print 'real life'
  conn = MTurkConnection()

def post_html_question(title, description, quals, num_tasks, price, q_url, 
  duration_s=120, keywords=None):
  """Wrapper for creating & posting 'ExternalQuestion' on MTurk.
     
     see git.to/externalq for Amazon's ExternalQuestion docs
     see git.to/createhit for boto's create_hit method

     quals -- Qualifications object list. Use build_quals to create.
     price -- float (IE, 0.05 for 5 cents)
     duration_s -- max number of seconds the HIT can take. 

     Return the resulting HITId or -1 on failure.   
  """  
  if keywords == None: 
    keywords = []

  question = ExternalQuestion(q_url, HTML_FRAME_HEIGHT)
  
  result = conn.create_hit(
    question=question,
    title=title,
    description=description,
    keywords=keywords,
    reward=Price(float(price)),
    max_assignments=num_tasks,
    duration=duration_s,
    qualifications=quals
  )
  return result[0].HITId or -1#resulting hit ID or broken

def get_answers(hit_id):
  """return a list of tuples (answer, worker_id, assignment_id)"""
  # TODO: Support >100, tasks/HIT. Here's how: first call getHit, get 
  # assignments, call get_assignments on every hundred and join them.

  assignments = conn.get_assignments(hit_id=hit_id, page_size=100)
  return [(assign.answers[0],
      	   assign.WorkerId,
           assign.AssignmentId) for assign in assignments]

def accept_and_pay(worker_id, assign_id, bonus_price=0.00, 
	   reason="Congratulations!"):
  """pays for assignment; returns False if something went wrong, else True"""
  try:
    result = conn.approve_assignment(assign_id)
    #TODO: make sure to avoid the possibility of paying the same bonus twice 
    if bonus_price > 0:
      conn.grant_bonus(worker_id, assign_id, Price(amount=bonus_price), reason)
  except MTurkRequestError:
    #TODO: less embarrasing error handling
    print "looks like this one was already paid for. or, any other error" 
    return False# no bonus if already paid for
  return True

def reject(assign_id, reason="That was not correct"):
  try:
    conn.reject_assignment(assign_id, reason)
    return True
  except BaseException:
    #TODO: Less disgustingly general exception here
    print "looks like this one was already rejected. or, any other error" 
    return False

############ Experiment-specific code: #######################################
def build_quals(accept_max=None, accept_min=None, max_done=None, min_done=None):
  """handles setting four useful (for this experiment) qualfications"""
  qualifications = Qualifications()
  #TODO: explore changing code below to *args style
  if accept_max is not None: 
    q = PercentAssignmentsApprovedRequirement('LessThanOrEqualTo', accept_max)
    q.required_to_preview = True
    qualifications.add(q)
  if accept_min is not None:
    q = PercentAssignmentsApprovedRequirement(
         'GreaterThanOrEqualTo', accept_min)
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

def create_ht_hits(qual_groups, base_price=0.05, heads='10c', tails='5c', 
 		   flip_but='false'):
  """Creates External Hits for an MTurk run
 
     qual_groups -- list of kw-arg dicts to be passed to build_quals
     base_price -- double (ie, 0.05)
     heads -- string, used website descriptors (IE, '10c')
     tails -- string, used website descriptors (IE, '5c')
     flip_but -- string, should the user have a coin-flip button? 'true/false'

     Return the HITIds list of generated HITs.
  """

  # make sure to encode ampersands, otherwise the ExternalQuestion schema gets
  # pretty angry: http://alexeymk.com/xsanyuri-doesnt-allow-ampersands
  q_url = EXTERNAL_Q_URL + "?" + urllib.quote_plus(urllib.urlencode({
            'heads'  : heads,
            'tails'  : tails,
            'flipGen': str(flip_but).lower(),
            'real'   : str(TEST_MODE).lower()
          }))
  
  desc = """Project Random is running a one-question quiz.
   	    Note: You may only participate in one ProjectRandom experiment."""
  title = "One quick question. Should take ~15 seconds."
  result_hits = []

  # wrap the above arguments into a single function 
  def projectrandom_q(quals):
    return post_html_question(title, desc, quals, 
      num_tasks=50, price=base_price, q_url=q_url, 
      keywords=["survey", "test", "easy", ])

  for group in qual_groups:
    # http://docs.python.org/tutorial/controlflow.html#unpacking-argument-lists
    group_name = str(group.values())

    result_hits.append((group, projectrandom_q(build_quals(**group))))
  
  return result_hits
 
def cheated(answer):
  return is_head(answer) != answer_lookup(answer, u'flip_true')

def cheated_for_profit(answer):
  return is_head(answer) and not answer_lookup(answer, u'flip_true')

def has_result(answer): # some edge-cases don't have results.
  return any(map(lambda ans: ans.QuestionIdentifier == u'result', answer[0]))

def is_head(answer): 
  return answer_lookup(answer, u'result')

def answer_lookup(answer, key): 
  """in multiple-part answer scenarios, use key to look up answer"""
  # with multiple rows, check all parts of answer
  right_part = filter(lambda ans: ans.QuestionIdentifier == key, answer[0])
  if len(right_part) != 1:
    #TODO: Cleaner error message here
    print "ERROR, WEIRD ANSWER!", answer
    for part in answer[0]:
      print part.QuestionIdentifier + ": " + part.FreeText
  return len(right_part) > 0 and right_part[0].FreeText == u'heads'

def print_csv(hit_list):
  """create CSV from hit_list of format [(group_name, hit_id)]"""
  results = [] 
  csv = "Name\tHit ID\t#Heads\t#Tails\t#Cheaters\t#Cheaters(for profit)"+\
      "\t#Blank Results\t%Heads\t#Participants\n"
  
  for hit in hit_list:
    # figure out what columns you need and change these as you go
    hit_results = get_answers(hit[1])
    num_blanks = len(filter((lambda x: not has_result(x)), hit_results))
    hit_results = filter(has_result, hit_results)
    num_heads = len(filter(is_head, hit_results))
    num_cheaters = len(filter(cheated, hit_results))
    num_cheatersfp = len(filter(cheated_for_profit, hit_results))
    num_tails = len(hit_results) - num_heads
    results.append((hit[0], hit[1], num_heads, num_tails, 
                    num_cheaters, num_cheatersfp, num_blanks))

  def to_csv(content): return str(content) + "\t"

  for hit in results:
    for entry in hit: csv += to_csv(entry)
    total = hit[2] + hit[3]
    csv += to_csv(100.0 * hit[2] / total)
    csv += to_csv(total)
    csv += "\n"

  print csv

def pay_for_work (h_list):
  if SAFETY_BREAK:
    print "Turn off safety break if you're really ready to pay."
    return False
  
  for hit in h_list:
    for answer in get_answers(hit[1]):
      if has_result(answer):
        bonus_size = BONUS_SIZE if is_head(answer) else 0.00
        if accept_and_pay(answer[1], answer[2], bonus_size):
          print "paid: %s (+%f)" % (answer[1], bonus_size)
      else:
        if reject(answer[2], "You didn't pick heads or tails."):
          print "rejected: %s" % (answer[1],)

############ Data, hiding in code for convenience ########################
#TODO: at the very least have a separate file for stored HITIds. 
#project random 1 (2c/4c)
hit_list = [("100%", u'1NDCZYKKHE0PJNCX38JN8DTG8KACRG'),
            ("98-99%", u'1HAP633YC83RR30ZYB26GFMFT755IX'),
            ("97/95%", u'1N97AIQ2ZZ01K2CAIXJSYNYCUMTCS4'),
            ("94-90%", u'11RRTAQZP9M7ILR60NFOV5EW3GS9XS'),
            ("<90%", u'1OV175GB5BN5PJJFP2D7UKK9ZA3FM6'),
            ("<20 Hits", u'13WZ947TADA2V76594ZT1WXIHB0P8U')
	   ]
#project random 2 (5c/10c)
hit_list2 = [('100%', u'11AS9XI8SHRYVT1MZZ7NNW1N6XS7PZ'), 
	     ('98-99%', u'17OS5STSYZ9JV521ZCMCN1RXBTE7QQ'), 
	     ('97-95%', u'16QPTY5534VQNAKMEAQ0G6UT2VXLA6'), 
	     ('94-90%', u'13B68VH8U8QA3OS0OA0GN6IJ509Y3F'),
             ('<90%', u'10ZS3NWEBR24K8ZKMK5JWEVEJGTVJF'), 
	     ('<20 Hits', u'1E4BDSOKPRYZVS52455VXTVRY5TVKE')
	    ]
#project random 3 (10c/15c)
hit_list3 = [('97-95%', u'1RT6LH7Q5FLRJSIPUG4GJSC06ZXYLH'),
             ('100%', u'1K6HBZZ2IHIZ7Q2LSJK3MVWAAMK805'),
            ]
#project random 4 (3c/8c)
hit_list4 = [('97-95%', u'1XO7N3IELR2D1B5GDK51R7PKZGLKD1'),
             ('100%', u'1FK4O8V51O4PTGOBWA0VGZWD6SXX1D'),
            ]
#project random 5 (5c/10c + coin flip button)
hit_list5 = [('100%', u'1562QNH137YXAW2OVS1A5SEIXFHAAX'),
             ('99-98%', u'1F84T4IXYPLW6J5QN89T4TJFG10SFN'),
             ('97-95%', u'1EZ0TQKF5LUFYTBUEHWKOM6WMOAPJ7'),
             ('94-90%', u'19UMGJ5XPBOZEYK2PYHKNA4ILDUMMC'),
             ('<90%', u'1BR8TING8UD2KJ1LYSFBMEJRHG0SGM'),
             ('<20 Hits', u'1SOBPNA2BH8ZD5JL4N7EVC0R0HCZM6')
	    ]

############ Code that is actually changed and run ######################
#TODO: Potentially have a __main__ method here
qual_groups = [{'accept_min': 100, 'min_done':20},
	       {'accept_max': 99, 'accept_min': 98, 'min_done':20},
	       {'accept_max': 97, 'accept_min': 98, 'min_done':20},
	       {'accept_max': 94, 'accept_min': 98, 'min_done':20},
	       {'accept_max': 89, 'accept_min': 98, 'min_done':20},
	       {'max_done': 19}
	      ]
# (1) generate the experiment: 
# print create_ht_hits(qual_groups, .05, '10c', '5c', False)
# (2) after experiment is run, print out aggregate-level results: 
# print_csv(hit_list5)
# (3) pay participants: 
# pay_for_work(hit_list5)

