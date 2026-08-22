(() => {
  const heartsEl = document.getElementById('hearts');
  const hpText = document.getElementById('hp-text');
  const foodEl = document.getElementById('food');
  const levelEl = document.getElementById('level');
  const xpProg = document.getElementById('xp-progress');
  const deathsEl = document.getElementById('deaths');
  const armorEl = document.getElementById('armor');
  const viewersEl = document.getElementById('viewers');
  const cpmEl = document.getElementById('cpm');
  const powerEl = document.getElementById('power');
  const effectsEl = document.getElementById('effects');
  const invPanel = document.getElementById('inventory-panel');
  const invGrid = document.getElementById('inv-grid');

  let useCustomHearts = false;

  // Detect custom heart images
  const testImg = new Image();
  testImg.onload = () => { useCustomHearts = true; };
  testImg.onerror = () => { useCustomHearts = false; };
  testImg.src = '/overlay/assets/heart.png';

  function renderHearts(health, maxHealth) {
    heartsEl.innerHTML = '';
    const fullHearts = Math.floor(health / 2);
    const half = health % 2 === 1;
    const totalSlots = Math.ceil(maxHealth / 2);

    for (let i = 0; i < totalSlots; i++) {
      const div = document.createElement('div');
      div.className = 'heart';
      if (useCustomHearts) {
        if (i < fullHearts) div.classList.add('img-full');
        else if (i === fullHearts && half) div.classList.add('img-half');
        else div.classList.add('img-empty');
      } else {
        if (i < fullHearts) div.classList.add('css-full');
        else if (i === fullHearts && half) div.classList.add('css-half');
        else div.classList.add('css-empty');
      }
      heartsEl.appendChild(div);
    }
    hpText.textContent = `${health.toFixed(1)} / ${maxHealth}`;
  }

  function renderInventory(inv) {
    if (!inv || !inv.slots) {
      invPanel.classList.add('hidden');
      return;
    }
    invPanel.classList.remove('hidden');
    invGrid.innerHTML = '';
    // 36 main + 4 armor + offhand roughly; we just show what we get
    const slots = inv.slots || [];
    for (let i = 0; i < Math.min(slots.length, 45); i++) {
      const s = slots[i];
      const cell = document.createElement('div');
      cell.className = 'inv-slot' + (s && s.id ? ' has-item' : '');
      if (s && s.id) {
        const name = (s.id.split(':').pop() || s.id).replace(/_/g, ' ');
        cell.innerHTML = `<span class="inv-count">${s.count > 1 ? s.count : ''}</span><span class="inv-name">${name}</span>`;
        cell.title = `${s.id} × ${s.count}`;
      }
      invGrid.appendChild(cell);
    }
  }

  function update(data) {
    const s = data.stats || {};
    renderHearts(s.health ?? 20, s.maxHealth ?? 20);
    foodEl.textContent = Math.floor(s.food ?? 20);
    levelEl.textContent = s.level ?? 0;
    xpProg.textContent = s.xpProgress != null ? `(${Math.floor((s.xpProgress || 0) * 100)}%)` : '';
    deathsEl.textContent = s.deaths ?? 0;
    armorEl.textContent = s.armor ?? 0;

    const m = data.metrics || {};
    viewersEl.textContent = m.viewers ?? 0;
    cpmEl.textContent = m.cpm ?? 0;
    powerEl.textContent = m.powerLevel ?? 0;

    // effects
    effectsEl.innerHTML = '';
    (s.effects || []).forEach(e => {
      const d = document.createElement('div');
      d.className = 'effect';
      d.textContent = e.name + (e.duration ? ` ${e.duration}s` : '');
      effectsEl.appendChild(d);
    });

    if (data.showInventory) {
      renderInventory(data.inventory);
    } else {
      invPanel.classList.add('hidden');
    }
  }

  // WebSocket preferred, fallback to polling
  let ws;
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'update' || msg.stats) update(msg);
      } catch (_) {}
    };
    ws.onclose = () => setTimeout(connect, 2000);
  }
  connect();

  // safety poll
  setInterval(async () => {
    try {
      const res = await fetch('/api/state');
      if (res.ok) update(await res.json());
    } catch (_) {}
  }, 2500);
})();
