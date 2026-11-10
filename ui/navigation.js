'use strict';
/* A history of visited locations, independent from settings and execution plans. */
class NavigationHistory{
 constructor(saved,allowed){this.offset=0;this.allowed=new Set(allowed);const entries=saved?.entries?.filter(p=>this.allowed.has(p));this.entries=entries?.length?entries.slice(-100):['overview'];this.index=Math.max(0,Math.min(saved?.index||0,this.entries.length-1))}
 get page(){return this.entries[this.index]}
 get canBack(){return this.index>0}
 get canForward(){return this.index<this.entries.length-1}
 visit(page){if(!this.allowed.has(page)||page===this.page)return false;this.entries.splice(this.index+1);this.entries.push(page);if(this.entries.length>100){this.entries.shift();this.offset++;}this.index=this.entries.length-1;return true}
 jump(index){if(!Number.isInteger(index)||index<0||index>=this.entries.length)return false;this.index=index;return true}
 value(){return {entries:[...this.entries],index:this.index}}
}
if(typeof module!=='undefined')module.exports=NavigationHistory;
