// Extracts tournamentLogs + alias maps from the site's index.html into JSON (stdout).
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[2],'utf8');
function grab(name){const i=html.indexOf('const '+name+' =');if(i<0)throw name;
  let j=html.indexOf('=',i)+1;let depth=0,k=j,started=false,q=null;
  for(;k<html.length;k++){const c=html[k];
    if(q){if(c==='\\'){k++;continue;} if(c===q)q=null;continue;}
    if(c==='"'||c==="'"||c==='`'){q=c;continue;}
    if(c==='['||c==='{'){depth++;started=true;} else if(c===']'||c==='}'){depth--; if(started&&depth===0){k++;break;}}}
  return vm.runInNewContext('('+html.slice(j,k)+')');}
const out={logs:grab('tournamentLogs'),name_aliases:grab('NAME_ALIASES'),school_aliases:grab('SCHOOL_ALIASES')};
process.stdout.write(JSON.stringify(out));
