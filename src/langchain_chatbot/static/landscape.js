// A seeded landscape, drawn at the resolution of the display.
export function drawLandscape(canvas) {
  const paint = () => {
    const {width, height} = canvas.getBoundingClientRect();
    if (!width || !height) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.scale(canvas.width / 760, canvas.height / 300);
    let seed = 5409;
    function rand() {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    }
    function stroke(points, color, lineWidth = 0.7) {
      ctx.beginPath();
      points.forEach(([x,y], i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y));
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;
      ctx.stroke();
    }
    const sky = ctx.createLinearGradient(0, 0, 0, 300);
    sky.addColorStop(0, "#dfe8d5");
    sky.addColorStop(0.75, "#f2e9cf");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, 760, 300);

    // The ochre sun is overprinted with fine, broken horizontal strokes.
    ctx.save();
    ctx.beginPath();
    ctx.arc(549, 72, 33, 0, Math.PI * 2);
    ctx.clip();
    ctx.fillStyle = "#dbad69";
    ctx.fillRect(512, 36, 74, 74);
    for (let y = 40; y < 109; y += 2.8) {
      stroke([[505,y],[590,y + rand()]], "#f0d19b", 0.8);
    }
    ctx.restore();
    for (let i = 0; i < 77; i++) {
      const x = rand() * 760, y = rand() * 143;
      stroke([[x,y],[x + 4 + rand() * 35,y - 0.5]], "#9eaa8b50", 0.6);
    }

    function terrain(anchors, fill, ink, variation, gap) {
      const ridge = [];
      let segment = 0;
      for (let x = 0; x <= 760; x += 2) {
        while (segment < anchors.length - 2 && x > anchors[segment+1][0]) segment++;
        const [ax,ay] = anchors[segment], [bx,by] = anchors[segment+1];
        const t = (x-ax)/(bx-ax);
        const elevation = ay + t*(by-ay) + variation*(Math.sin(x*.081)+0.6*Math.sin(x*.23)+.4*(rand()-.5));
        ridge.push([x,elevation]);
      }
      ctx.beginPath();
      ctx.moveTo(0,306);
      for (const [x,y] of ridge) ctx.lineTo(x,y);
      ctx.lineTo(760,306);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.save();
      ctx.clip();
      stroke(ridge, ink, 1);
      for (let depth = 1; depth < 105; depth += gap) {
        const contour = ridge.map(([x,y]) => [
          x - depth * .24 * Math.sin(x/170), y + depth * (1.3 + .4*Math.sin(x/83))
            + Math.sin(x/13 + depth/7)*Math.min(depth/9,1.6),
        ]);
        stroke(contour, ink, .65);
      }
      ctx.restore();
      return ridge;
    }
    terrain([[0,191],[96,174],[146,186],[213,151],[247,164],[305,119],[336,132],[384,102],[407,116],[433,104],[476,133],[508,120],[579,155],[655,129],[693,138],[760,117]], "#cad6b9", "#819878", 2.9, 4.2);
    terrain([[0,227],[85,208],[148,224],[214,188],[270,205],[344,163],[377,177],[420,161],[467,174],[510,155],[558,137],[599,151],[659,120],[702,140],[760,127]], "#adbea0", "#6c896b", 2.4, 3.6);
    terrain([[0,251],[70,240],[132,251],[193,226],[255,237],[313,222],[364,226],[407,209],[453,218],[506,198],[563,209],[612,198],[665,204],[714,181],[760,187]], "#90a789", "#557660", 1.8, 4);

    // Fine-edged evergreens give the foreground a scale against the hills.
    function pine(x, y, h, color) {
      const w = h * (0.14 + rand() * 0.035);
      stroke([[x,y],[x+0.5,y-h]], color, Math.max(0.55,h*0.025));
      for (let t = .14; t < .91; t += .071) {
        const branchY = y-h+h*t, span = w*t;
        stroke([[x-span*(.65+rand()*.5),branchY+h*.075],[x,branchY],[x+span*(.65+rand()*.5),branchY+h*.07]], color, Math.max(.6,h*.025));
      }
    }
    const middle = terrain([[0,258],[108,246],[175,254],[250,245],[325,249],[399,231],[470,239],[542,220],[607,227],[659,209],[716,204],[760,189]], "#7c987c", "#486d58", 1.4, 5);
    for (let i=0; i<280; i++) {
      const [x,y] = middle[Math.floor(rand()*middle.length)];
      pine(x,y+6,4+rand()*19,"#52735b");
    }
    const front = terrain([[0,280],[90,263],[184,276],[282,260],[350,269],[431,250],[500,263],[570,247],[632,249],[699,229],[760,217]], "#68866c", "#3d634e", 1.2, 5);
    for (let i=0; i<185; i++) {
      const [x,y] = front[Math.floor(rand()*front.length)];
      pine(x,y+10,7+rand()*25,"#3e644f");
    }
    for (const [x,y,h] of [[681,262,49],[701,257,63],[728,252,88],[751,242,66],[385,280,32],[348,274,25]]) {
      pine(x,y,h,"#335441");
    }
    for (let i=0; i<12500; i++) {
      ctx.fillStyle = i%2 ? "#264d3020" : "#fffbe832";
      ctx.fillRect(rand()*760,rand()*300,.7,.7);
    }
  };
  new ResizeObserver(paint).observe(canvas);
  paint();
}
