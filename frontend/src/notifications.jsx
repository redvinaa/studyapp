import React,{useEffect,useRef,useState} from 'react';
import {X} from 'lucide-react';

export function Notifications({children}){
 return <div className="notifications">{children}</div>;
}

export function Notice({message,kind='error',children}){
 const [phase,setPhase]=useState('visible'),[paused,setPaused]=useState(false);
 const duration=children?10000:6000;
 useEffect(()=>setPhase('visible'),[message]);
 useEffect(()=>{
  if(!message||paused||phase!=='visible')return;
  const timer=setTimeout(()=>setPhase('leaving'),duration);
  return()=>clearTimeout(timer);
 },[message,paused,duration,phase]);
 useEffect(()=>{
  if(phase!=='leaving')return;
  const timer=setTimeout(()=>setPhase('hidden'),180);
  return()=>clearTimeout(timer);
 },[phase]);
 if(!message||phase==='hidden')return null;
 return <div className={'toast '+phase} data-kind={kind} role={kind==='error'?'alert':'status'} onMouseEnter={()=>setPaused(true)} onMouseLeave={()=>setPaused(false)} onFocusCapture={()=>setPaused(true)} onBlurCapture={e=>{if(!e.currentTarget.contains(e.relatedTarget))setPaused(false)}}><span className="toast-message">{message}</span>{children&&<span className="toast-actions">{children}</span>}<button type="button" className="toast-dismiss" aria-label="Dismiss notification" onClick={()=>setPhase('leaving')}><X size={16}/></button></div>;
}

export function BackgroundErrors({tree}){
 const seen=useRef(new Set()),sequence=useRef(0),[notices,setNotices]=useState([]);
 useEffect(()=>{
  const current=new Set(),fresh=[];
  for(const course of tree)for(const topic of course.topics){
   const errors=[];
   if(topic.index_status==='error')errors.push({key:'topic:'+topic.id,message:topic.last_error||'Indexing failed.'});
   for(const job of topic.generations||[])if(job.status==='failed')errors.push({key:'generation:'+job.id,message:job.error||'Material generation failed.'});
   for(const error of errors){
    const key=error.key+':'+error.message;
    current.add(key);
    if(!seen.current.has(key))fresh.push({id:++sequence.current,message:topic.name+': '+error.message});
   }
  }
  seen.current=current;
  if(fresh.length)setNotices(old=>[...old,...fresh].slice(-3));
 },[tree]);
 return notices.map(notice=><Notice key={notice.id} message={notice.message}/>);
}
