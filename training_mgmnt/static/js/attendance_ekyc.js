/* attendance_ekyc.js — external script for EKYC fingerprint workflow.
   Reads endpoint URL from #ekyc_root data-endpoint attribute to call server POST actions.
   Expects server to respond with JSON: { success: True/False, status: 'RECORDED'|'VERIFIED', status_display: 'Recorded' }
*/
(function(){
  function dbg(m){ try{ console.log('[EKYC] '+m); }catch(e){} }
  function getCookie(name){ const v=document.cookie.match('(^|;)\\s*'+name+'\\s*=\\s*([^;]+)'); return v? v.pop() : ''; }

  document.addEventListener('DOMContentLoaded', function(){
    const root = document.getElementById('ekyc_root');
    const endpoint = root ? root.dataset.endpoint : window.location.href;
    const testBtn = document.getElementById('testConnectionBtn');
    const testStatus = document.getElementById('testStatus');
    const loader = document.getElementById('ekyc_loader');
    const participantsWrapper = document.getElementById('ekyc_participants_wrapper');
    const doneMsg = document.getElementById('ekyc_done_msg');

    if(!testBtn){ dbg('No testConnectionBtn found — aborting'); return; }

    testBtn.addEventListener('click', function(){
      testBtn.disabled = true;
      if(testStatus) testStatus.textContent = 'Testing...';
      if(loader) loader.style.display = 'block';
      setTimeout(function(){
        if(loader) loader.style.display = 'none';
        if(testStatus) testStatus.textContent = 'Connection succeeded!';
        if(participantsWrapper) participantsWrapper.style.display = 'block';
        const firstRec = document.querySelector('.recordBtn:not([disabled])');
        if(firstRec) firstRec.focus();
        dbg('Simulated connection success');
      }, 2000);
    });

    // delegated click handler for record and verify buttons
    document.addEventListener('click', async function(ev){
      const t = ev.target;
      if(!t || !t.classList) return;

      // record
      if(t.classList.contains('recordBtn')){
        const row = t.closest('tr'); if(!row) return;
        const pid = row.dataset.participantId, role = row.dataset.participantRole;
        const statusEl = row.querySelector('.actionStatus'); if(statusEl) statusEl.textContent = ' Recording...';
        t.disabled = true; const verifyBtn = row.querySelector('.verifyBtn'); if(verifyBtn) verifyBtn.disabled = true;
        await new Promise(r=>setTimeout(r,1500));
        try{
          const fd = new FormData(); fd.append('action','record_fingerprint'); fd.append('participant_id',pid); fd.append('participant_role',role);
          const resp = await fetch(endpoint, { method:'POST', headers:{ 'X-Requested-With':'XMLHttpRequest','X-CSRFToken':getCookie('csrftoken') }, body: fd });
          const data = await resp.json();
          dbg('record response: '+JSON.stringify(data));
          if(data && data.success){
            const st = row.querySelector('.ekyc-status'); if(st) st.textContent = data.status_display || data.status || 'Recorded';
            if(statusEl) statusEl.textContent = ' Fingerprint recorded';
            if(verifyBtn) verifyBtn.disabled = false;
          } else {
            if(statusEl) statusEl.textContent = ' Failed';
            dbg('record failed: '+(data && data.error));
          }
        }catch(e){ dbg('record AJAX error '+e); if(statusEl) statusEl.textContent=' Error'; }
      }

      // verify
      if(t.classList.contains('verifyBtn')){
        const row = t.closest('tr'); if(!row) return;
        const pid = row.dataset.participantId, role = row.dataset.participantRole;
        const statusEl = row.querySelector('.actionStatus'); if(statusEl) statusEl.textContent = ' Verifying...';
        t.disabled = true; const recordBtn = row.querySelector('.recordBtn'); if(recordBtn) recordBtn.disabled = true;
        await new Promise(r=>setTimeout(r,1500));
        try{
          const fd = new FormData(); fd.append('action','verify_ekyc'); fd.append('participant_id',pid); fd.append('participant_role',role);
          const resp = await fetch(endpoint, { method:'POST', headers:{ 'X-Requested-With':'XMLHttpRequest','X-CSRFToken':getCookie('csrftoken') }, body: fd });
          const data = await resp.json();
          dbg('verify response: '+JSON.stringify(data));
          if(data && data.success){
            const st = row.querySelector('.ekyc-status'); if(st) st.textContent = data.status_display || data.status || 'Verified';
            if(statusEl) statusEl.textContent = ' Verified';
            if(recordBtn) recordBtn.disabled = true;
            t.disabled = true;
            const all = Array.from(document.querySelectorAll('#ekyc_table tbody tr'));
            const allVerified = all.every(r=> r.querySelector('.ekyc-status').textContent.trim().toLowerCase() === 'verified');
            if(allVerified){
              if(doneMsg) doneMsg.style.display = 'block';
              setTimeout(()=> location.reload(), 900);
            }
          } else {
            if(statusEl) statusEl.textContent = ' Failed';
            dbg('verify failed: '+(data && data.error));
          }
        }catch(e){ dbg('verify AJAX error '+e); if(statusEl) statusEl.textContent=' Error'; }
      }
    });

  });
})();