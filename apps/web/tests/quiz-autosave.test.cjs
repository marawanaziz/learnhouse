const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const React=require('react');const {act,create}=require('react-test-renderer');
const ts=require('typescript');
global.IS_REACT_ACT_ENVIRONMENT=true;
const prefix=require('node:path').resolve(__dirname,'..')+'/';
const file=prefix+'app/orgs/[orgslug]/dash/assignments/[assignmentuuid]/_components/TaskEditor/Subs/TaskTypes/TaskQuizObject.tsx';
const questions=[1,2].map(i=>({questionText:'Q'+i,questionUUID:'q'+i,options:[{optionUUID:'a'+i,text:'A',assigned_right_answer:true},{optionUUID:'b'+i,text:'B',assigned_right_answer:false}]}));
let batch={},save,resolveSave,payloads=[],state={};const noop=()=>{};const assignment={assignment_object:{assignment_uuid:'assignment_qa'},assignment_tasks:[{assignment_task_uuid:'task_qa',contents:{questions},max_grade_value:100}]};
function compile(path,req){const m={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText,{module:m,exports:m.exports,require:req,setTimeout:()=>1,clearTimeout:noop,console});return m.exports;}
const selection=compile(prefix+'lib/assignments/quizSelection.ts',()=>{});
const stubs={
 '@components/Contexts/Assignments/AssignmentContext':{useAssignments:()=>assignment},
 '@components/Contexts/Assignments/AssignmentSubmissionContext':{useAssignmentSubmission:()=>[],useAssignmentTaskSubmissions:()=>batch},
 '@components/Contexts/Assignments/AssignmentsTaskContext':{useAssignmentsTask:()=>state,useAssignmentsTaskDispatch:()=>noop},
 '@components/Contexts/LHSessionContext':{useLHSession:()=>({data:{tokens:{access_token:'qa'}}})},
 '@components/Objects/Activities/Assignment/AssignmentBoxUI':({children})=>React.createElement('section',null,children),
 '@services/courses/assignments':{handleAssignmentTaskSubmission:async(values)=>{payloads.push(values);return new Promise(r=>resolveSave=r);}},
 'lucide-react':new Proxy({},{get:()=>noop}),react:React,'react-hot-toast':{error:noop,success:noop},uuid:{v4:()=>''},'react-i18next':{useTranslation:()=>({t:x=>x})},
 '@tanstack/react-query':{useQueryClient:()=>client},'@/lib/query/keys':{queryKeys:{assignments:{taskSubmission:()=>['qa']}}},'./applyManualGrade':{},
 '@/lib/assignments/draftSaveRegistry':{registerAssignmentDraftSave:(a,t,fn)=>{save=fn;return noop;}},'@/lib/assignments/quizSelection':selection
};const client={invalidateQueries:noop};
const Component=compile(process.env.QUIZ_TEST_SOURCE || file,n=>{if(!(n in stubs))throw Error(n);return stubs[n];}).default;
let renderer;const render=async(key='attempt1')=>{await act(async()=>{const el=React.createElement(Component,{view:'student',assignmentTaskUUID:'task_qa',key});if(renderer)renderer.update(el);else renderer=create(el);});};
const radios=()=>renderer.root.findAll(x=>x.props.role==='radio');const chosen=()=>radios().map(x=>!!x.props['aria-checked']);
(async()=>{
 await render();await act(async()=>{radios()[0].props.onClick();});
 let pending;await act(async()=>{pending=save();await Promise.resolve();});
 await act(async()=>{radios()[2].props.onClick();});
 await act(async()=>{resolveSave({success:true,data:{assignment_task_submission_uuid:'saved'}});await pending;});
 batch={task_qa:{task_submission:payloads[0].task_submission,assignment_task_submission_uuid:'saved'}};state={reloaded:true};await render();
 assert.deepEqual(chosen(),[true,false,true,false],'an old autosave snapshot must not erase a later answer');
 await act(async()=>{pending=save();await Promise.resolve();});assert.equal(payloads[1].task_submission.submissions.filter(x=>x.answer).length,2);
 await act(async()=>{resolveSave({success:true,data:{assignment_task_submission_uuid:'saved'}});await pending;});
 console.log('PASS: in-flight save and later context refresh preserve newer answer and persist both');
 batch={};await render('attempt2');assert.deepEqual(chosen(),[false,false,false,false]);console.log('PASS: native attempt remount starts with no previous selections');
 batch=null;await render('attempt3');await act(async()=>{radios()[2].props.onClick();});batch={task_qa:{task_submission:payloads[0].task_submission,assignment_task_submission_uuid:'saved'}};await render('attempt3');assert.deepEqual(chosen(),[false,false,true,false]);console.log('PASS: delayed initial server snapshot cannot overwrite learner input');
 await act(async()=>renderer.unmount());
})().catch(e=>{console.error(e);process.exitCode=1;});
