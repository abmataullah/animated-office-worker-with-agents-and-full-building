#!/usr/bin/env node
/*
  Local feed for office-widget.html. No dependencies.

  Run:   node feed/pc-feed.js        (default port 8765, override with PORT=...)
  Open:  office-widget.html          (it polls http://localhost:8765/state by itself)

  Two sources of events:
    1. Process scan: if an app from RULES is running, its worker gets a job.
       This only proves the app is open. ffmpeg, HandBrake and Media Encoder
       exist only while a render runs, so they are a stronger signal than Premiere.
    2. POST /event: anything else (Facebook ads, email tools, n8n, Zapier, scripts)
       pushes its own status. Facebook workflows cannot be detected from the OS.

  POST /event  {"id":"fb-1","cat":"ads","task":"Retargeting campaign","progress":40,
                "status":"running","ttl":120}
    cat:    ads video design writing sheets backup email social media docs web data
    agent:  optional worker name, overrides cat (for example "Jim")
    status: "running" (default) or "done"
    ttl:    seconds to keep a running event without a refresh (default 120)
*/
const http=require('http');
const {execFile}=require('child_process');
const path=require('path');

const PORT=Number(process.env.PORT)||8765;
const WIN=process.platform==='win32';

const RULES=[
  {cat:'video',label:'Video',names:['premiere','afterfx','media encoder','ffmpeg','handbrake','davinci','obs64']},
  {cat:'design',label:'Graphics',names:['photoshop','illustrator','lightroom','canva','figma']},
  {cat:'writing',label:'Writing',names:['winword','notion','obsidian','scrivener']},
  {cat:'sheets',label:'Sheets',names:['excel']},
  {cat:'backup',label:'Backup',names:['dropbox','onedrive','googledrivefs','backup']},
  {cat:'media',label:'Audio',names:['audacity','reaper','garageband']},
  {cat:'docs',label:'Documents',names:['acrobat','acrord','powerpnt']},
];

const posted=new Map();   // id -> {event, expires}
let detected=[];

function listProcesses(cb){
  if(WIN){
    execFile('tasklist',['/fo','csv','/nh'],{maxBuffer:8e6},(err,out)=>{
      if(err)return cb([]);
      cb(out.split(/\r?\n/).map(l=>(l.match(/^"([^"]+)"/)||[])[1]).filter(Boolean));
    });
  }else{
    execFile('ps',['-A','-o','comm='],{maxBuffer:8e6},(err,out)=>{
      if(err)return cb([]);
      cb(out.split('\n').map(l=>path.basename(l.trim())).filter(Boolean));
    });
  }
}
function scan(){
  listProcesses(procs=>{
    const low=procs.map(p=>p.toLowerCase());
    const found=[];
    for(const r of RULES){
      const hit=low.find(p=>r.names.some(n=>new RegExp('(^|[ .\\-])'+n.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).test(p)));
      if(hit)found.push({id:'proc:'+r.cat,cat:r.cat,task:`${r.label}: ${procs[low.indexOf(hit)]} is running`,progress:null,status:'running'});
    }
    detected=found;
  });
}
scan();setInterval(scan,3000);

function state(){
  const now=Date.now(),out=[];
  for(const[id,v] of posted){
    if(v.expires<now){posted.delete(id);continue;}
    out.push(v.event);
  }
  const ids=new Set(out.map(e=>e.id));
  for(const d of detected)if(!ids.has(d.id))out.push(d);
  return{source:'pc-feed',events:out};
}

function cors(res){
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Access-Control-Allow-Methods','GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers','content-type');
}
http.createServer((req,res)=>{
  cors(res);
  if(req.method==='OPTIONS'){res.writeHead(204);return res.end();}
  if(req.method==='GET'&&req.url.split('?')[0]==='/state'){
    res.writeHead(200,{'Content-Type':'application/json'});
    return res.end(JSON.stringify(state()));
  }
  if(req.method==='POST'&&req.url.split('?')[0]==='/event'){
    let body='';
    req.on('data',c=>{body+=c;if(body.length>20000)req.destroy();});
    req.on('end',()=>{
      try{
        const e=JSON.parse(body);
        if(!e||typeof e.task!=='string'||(!e.cat&&!e.agent))throw new Error('need task and cat or agent');
        const id=String(e.id||`${e.agent||e.cat}:${e.task}`).slice(0,120);
        const status=e.status==='done'?'done':'running';
        const ttl=status==='done'?30:Math.min(Number(e.ttl)||120,3600);
        posted.set(id,{event:{id,cat:e.cat,agent:e.agent,task:e.task.slice(0,120),
          progress:typeof e.progress==='number'?e.progress:null,status},expires:Date.now()+ttl*1000});
        res.writeHead(200,{'Content-Type':'application/json'});res.end('{"ok":true}');
      }catch(err){
        res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:err.message}));
      }
    });
    return;
  }
  res.writeHead(404);res.end();
}).listen(PORT,'127.0.0.1',()=>console.log(`pc-feed listening on http://localhost:${PORT}/state`));
