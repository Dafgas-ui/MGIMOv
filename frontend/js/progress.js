// Animate emphasis only: semantic and visible numbers always have their real value.
export function emphasizeProgress(meter,host=globalThis){
  if(host.matchMedia?.('(prefers-reduced-motion: reduce)').matches||!meter.animate)return;
  meter.animate([{opacity:.55},{opacity:1}],{duration:220,easing:'cubic-bezier(0.23, 1, 0.32, 1)'});
}
