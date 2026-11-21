// node render.js -> video.mp4 (silent master) + slides/*.png
const {chromium}=require('playwright');const {spawn}=require('child_process');const fs=require('fs');
(async()=>{
  const b=await chromium.launch();const p=await b.newPage({viewport:{width:1080,height:1920}});
  await p.goto('file://'+__dirname+'/index.html');await p.waitForTimeout(1500);
  const {TOTAL,T0,D}=await p.evaluate(()=>({TOTAL,T0,D}));
  fs.mkdirSync(__dirname+'/slides',{recursive:true});
  for(let i=0;i<D.length;i++){await p.evaluate(t=>seek(t),T0[i]+D[i]-0.3);await p.screenshot({path:`${__dirname}/slides/${String(i+1).padStart(2,'0')}.png`})}
  const ff=spawn('ffmpeg',['-y','-loglevel','error','-f','image2pipe','-framerate','30','-i','-','-c:v','libx264','-preset','veryfast','-crf','17','-pix_fmt','yuv420p',__dirname+'/video.mp4'],{stdio:['pipe','inherit','inherit']});
  const n=Math.round(TOTAL*30);
  for(let f=0;f<n;f++){await p.evaluate(t=>seek(t),f/30);const buf=await p.screenshot({type:'jpeg',quality:92});if(!ff.stdin.write(buf))await new Promise(r=>ff.stdin.once('drain',r))}
  ff.stdin.end();await new Promise(r=>ff.on('close',r));await b.close();console.log('frames',n);
})();
