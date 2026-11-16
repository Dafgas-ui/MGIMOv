import {requestJson} from './api.js';
import {t} from './language.js';

export const courseworkPath = role => '/api/v1/'+(role==='student'?'me':'staff')+'/coursework';
export const unicodeLength = value => [...value].length;
export const submissionBodyFits = body => new TextEncoder().encode(JSON.stringify(body)).length <= 32768;

export function filterWorks(items, {semester='', subject=''} = {}) {
  return items.filter(item => (!semester || item.semester_id===semester) && (!subject || item.subject_name===subject));
}

export function courseworkError(error) {
  if(error.code==='coursework_brs_result_already_published')
    return t('По мероприятию уже опубликованы результаты БРС. Задание осталось черновиком.',
             'BRS results already exist for this event. The assignment is still a draft.');
  const labels={
    401:['Сессия завершена. Войдите снова.','Your session expired. Sign in again.'],
    403:['Доступ к действию запрещён.','Access to this action is denied.'],
    404:['Работа или получатель недоступны.','The assignment or recipient is unavailable.'],
    409:['Данные изменились или действие сейчас недоступно. Обновите данные перед повтором.',
         'The data changed or the action is unavailable. Refresh before trying again.'],
    413:['Тело запроса слишком большое. Сократите текст.','The request is too large. Shorten the text.'],
    415:['Сервер не поддерживает формат запроса. Для этой операции требуется JSON.',
         'The server does not support this request format. This action requires JSON.'],
    422:['Проверьте заполнение полей.','Check the values you entered.'],
    503:['Сервис временно недоступен. Повторите позже.','The service is temporarily unavailable. Try again later.']
  };
  return t(...(labels[error.status]||['Ответ не получен. Можно повторить ту же операцию.','No response received. You can retry the same action.']));
}

export function createCourseworkClient(user, csrf, request=requestJson, makeKey=()=>crypto.randomUUID()) {
  const base=courseworkPath(user.role);
  const headers=()=>({'X-Mgimov-User':user.id});
  let pending=null, sending=false, conflicted=false;
  return {
    read(path='', signal) {return request(base+path,{headers:headers(),signal});},
    refreshed() {conflicted=false;},
    async write(path, method, fields) {
      if(sending||conflicted)return null;
      const signature=JSON.stringify([method,path,fields]);
      if(pending && pending.signature!==signature)
        throw new Error('retry-original');
      const body=pending?.body||{...fields,request_key:makeKey()};
      if(path.endsWith('/submissions')&&!submissionBodyFits(body))
        throw Object.assign(new Error('body-size'),{status:413});
      pending={signature,body};
      sending=true;
      try {
        const result=await request(base+path,{method,body,headers:{...headers(),'X-CSRF-Token':csrf()}});
        pending=null;
        return result;
      }catch(error){
        if(error.status===409)conflicted=true;
        if(error.status&&error.status<500&&error.status!==408)pending=null;
        throw error;
      }finally{sending=false;}
    }
  };
}
