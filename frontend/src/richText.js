// Normalize common LaTeX delimiters without changing literal code examples.
export function normalizeMath(text='') {
 return String(text).split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g).map((part,i)=>i%2?part:part
  .replace(/\\\[([\s\S]*?)\\\]/g,(_,math)=>'\n$$\n'+math.trim()+'\n$$\n')
  .replace(/\\\(([\s\S]*?)\\\)/g,(_,math)=>'$'+math.trim()+'$')
  .replace(/(^|\n)[ \t]*\[\s*([\s\S]*?)\s*\][ \t]*(?=\n|$)/g,(whole,start,math)=>/\\[a-zA-Z]+/.test(math)?start+'\n$$\n'+math.trim()+'\n$$\n':whole)
 ).join('');
}
