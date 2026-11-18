"""Synthetic 20/20/20/40 courses shared by HTTP and browser tests."""
import secrets
from backend.brs import service, models, results
from backend.academics import attestation
from backend.db import connection

ADMIN={'id':'admin','role':'staff'}
TEACHER={'id':'teacher','role':'staff'}


def prepare(case):
    courses={}
    with connection(case.settings,write=True) as db:
        db.execute("UPDATE curriculum_items SET control='credit' WHERE id='law-s'")
        db.execute("INSERT INTO subjects VALUES ('diff','Differentiated course')")
        db.execute("INSERT INTO curriculum_items VALUES ('diff-s','p','diff','s','graded_credit',1)")
        db.execute("INSERT INTO lessons VALUES ('ld','a','diff','t','room','2027-03-02',540,600,'lecture','scheduled',1,?)",(case.now,))
        service.bind_teacher(db,ADMIN,case.now,{'staff_id':'teacher','teacher_id':'t','lesson_id':'l'})
        for curriculum,control,lesson in [('math-s','exam','l'),('law-s','credit','ll'),('diff-s','graded_credit','ld')]:
            plan=case.plan()
            plan.update(curriculum_id=curriculum,admission_min=50,rounding='exact')
            plan['categories']=[{'code':f'c{i}','title':f'Category {i+1}','maximum':n} for i,n in enumerate((20,20,20,40))]
            plan['events']=[{**row,'category_code':row['code'],'attempt_limit':2 if i<2 else 1,
                'retake_policy':('highest' if i==0 else 'latest') if i<2 else 'none',
                'retake_until':'2027-06-20' if i<2 else None} for i,row in enumerate(plan['categories'])]
            plan['scale']=[{'minimum':n,'outcome':v} for n,v in (
                [(0,'fail'),(50,'pass')] if control=='credit' else [(0,'2'),(50,'3'),(65,'4'),(80,'5')])]
            key=service.create_plan(db,ADMIN,case.now,models.Plan(**plan).model_dump())['id']
            service.lock_plan(db,ADMIN,case.now,key)
            offering=service.create_offering(db,ADMIN,case.now,{'plan_id':key,'group_id':'a'})['id']
            enrolled=service.enroll(db,ADMIN,case.now,offering,{'student_id':'alice','starts_on':'2027-02-01'})
            service.grant_teaching(db,ADMIN,case.now,offering,{'staff_id':'teacher','lesson_id':lesson,
                'lesson_version':1,'expires_at':case.now+3600,'can_confirm_final':True,'event_code':None})
            attestation.approve_policy(db,ADMIN,case.now,key,[])
            courses[control]={**enrolled,'offering':offering,'plan':key}
    return courses


def publish(db,case,course,code,points,attempt=1):
    args=(course['offering'],course['id'],code,attempt)
    state=results.staff_result(db,TEACHER,case.now,*args[:3])
    draft=results.save_draft(db,TEACHER,case.now,*args,{'points':points,'expected_draft_version':0})
    return results.change_result(db,TEACHER,case.now,*args,{'request_key':secrets.token_hex(16),
        'expected_result_version':state['result_version'],'expected_draft_version':draft['draft_version']},command='publish')


def total(db,case,course,value):
    for i,maximum in enumerate((20,20,20,40)):
        points=min(value,maximum);value-=points
        publish(db,case,course,f'c{i}',points)
