export function shotQuality(result={}) {
  const parts=[];
  if(result.native_width&&result.native_height)parts.push(`原生 ${result.native_width}×${result.native_height}`);
  if(result.enhancement?.applied)parts.push('已做AI细节修复');
  if(result.coverage_count>1)parts.push(`自动安排${result.coverage_count}段画面`);
  if(result.timing?.pause_aligned_cuts)parts.push(`${result.timing.pause_aligned_cuts}处切镜对齐对白停顿`);
  if(result.enhancement?.frames_reused)parts.push('已接回上次修复进度');
  const quality=result.quality;
  if(quality?.status==='passed')parts.push('抽样检查通过');
  else if(quality?.status==='warning')parts.push('待人工复核（自动检查可能误判）：'+(quality.issues?.[0]?.evidence||'有细节待核对'));
  else if(quality?.status==='rejected')parts.push('画面检查未通过');
  return parts.join(' · ');
}

export function filmQuality(film={}) {
  const parts=[`导出 ${film.width}×${film.height}`,`${Math.round(film.seconds||0)}秒`];
  const sizes=film.quality?.native_sizes||((film.native_width&&film.native_height)?[[film.native_width,film.native_height]]:[]);
  if(sizes.length)parts.push('原生 '+sizes.map(([w,h])=>`${w}×${h}`).join(' / '));
  if(film.quality?.ai_upscaled)parts.push('AI修复放大');
  else if(film.resize_method)parts.push('缩放导出');
  if(film.quality?.needs_review)parts.push(`${film.quality.needs_review}镜待人工复核，自动检查可能误判`);
  if(film.quality)parts.push(`抽样检查通过 ${film.quality.reviewed}/${film.quality.total}镜`);
  return parts.join(' · ');
}
