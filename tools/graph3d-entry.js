import ForceGraph3D from '3d-force-graph';
import SpriteText from 'three-spritetext';

// Rendering only: data never leaves the browser, and simulation never mutates saved graphs.
window.PaperGraph3D = {
  create(host, nodes, edges, select, options={}) {
    let focus = '', near = new Set(), disposed = false;
    const id = value => typeof value === 'object' ? value.id : value;
    let data = {nodes: nodes.map(n => ({...n})), links: edges.map(e => ({...e}))};
    const graph = new ForceGraph3D(host, {controlType:'orbit'})
      .width(host.clientWidth).height(host.clientHeight)
      .backgroundColor('#f5f7fb').showNavInfo(false)
      .nodeLabel(() => '').linkLabel(() => '')
      .nodeVal(n => n.graphSize).nodeResolution(12)
      .nodeColor(n => n.id === focus ? '#563775' : focus && !near.has(n.id) ? '#d9e1ec' : n.graphColor)
      .linkColor(e => !focus ? (e.priority===3?'#7788ba':'#a5b4cb') : id(e.source) === focus || id(e.target) === focus ? '#8b679f' : '#dce3ed')
      .linkVisibility(e => !focus||id(e.source)===focus||id(e.target)===focus)
      .nodeOpacity(1).linkOpacity(.8).linkWidth(e => focus && (id(e.source) === focus || id(e.target) === focus) ? 1.6 : .4+(e.priority||1)*.18)
      .nodeThreeObjectExtend(true).nodeThreeObject(n => {
        const sprite = new SpriteText((n.starred?'★ ':n.liked?'♥ ':'')+n.label);
        // Keep distant labels readable instead of shrinking them with depth.
        sprite.color = '#25344e';sprite.textHeight = .021;sprite.material.sizeAttenuation = false;
        sprite.position.y = 4*Math.cbrt(n.graphSize)+5;
        sprite.fontFace = 'system-ui, sans-serif';sprite.backgroundColor = '#f5f7fbcc';sprite.padding = .0023;
        n.labelSprite = sprite;return sprite;
      })
      .onNodeClick(n => select(n.id)).onBackgroundClick(() => select(''))
      .onNodeDragEnd(n => { n.fx=n.x;n.fy=n.y;n.fz=n.z; })
      .warmupTicks(Math.min(100, nodes.length * 3)).cooldownTicks(100)
      .graphData(data);
    graph.d3Force('link').distance(110);
    graph.d3Force('charge').strength(-100);
    const observer = new ResizeObserver(() => {
      if (!disposed && host.clientWidth) graph.width(host.clientWidth).height(host.clientHeight);
    });observer.observe(host);
    let fitted=false,interacted=false;
    const interaction=()=>{interacted=true;};host.addEventListener('pointerdown',interaction);host.addEventListener('wheel',interaction,{passive:true});
    graph.onEngineStop(()=>{if(!fitted&&!disposed&&!interacted){fitted=true;graph.zoomToFit(500,55);}});
    const timer = setTimeout(() => {if(!disposed)graph.zoomToFit(500,65);}, 400);
    const visibility = () => document.hidden ? graph.pauseAnimation() : graph.resumeAnimation();
    document.addEventListener('visibilitychange', visibility);
    const positions = new Map();
    return {
      update(nodes, edges) {
        for(const n of data.nodes)if(Number.isFinite(n.x))positions.set(n.id,{x:n.x,y:n.y,z:n.z});
        const byId=new Map(data.nodes.map(n=>[n.id,n]));
        const next=nodes.map(n=>{
          const previous=byId.get(n.id),position=positions.get(n.id);
          if(previous){Object.assign(previous,n);previous.fx=previous.x;previous.fy=previous.y;previous.fz=previous.z;return previous;}
          if(position)return {...n,...position,fx:position.x,fy:position.y,fz:position.z};
          const neighbors=edges.filter(e=>e.source===n.id||e.target===n.id).map(e=>positions.get(e.source===n.id?e.target:e.source)).filter(Boolean);
          const anchor=neighbors[0];
          return {...n,...(anchor?{x:anchor.x+45,y:anchor.y+45,z:anchor.z+45}:{})};
        });
        data={nodes:next,links:edges.map(e=>({...e}))};
        graph.graphData(data);
      },
      setFocus(value) {
        focus=value;near=new Set(value?[value]:[]);
        for(const e of data.links)if(id(e.source)===focus||id(e.target)===focus){near.add(id(e.source));near.add(id(e.target));}
        graph.linkVisibility(graph.linkVisibility());
        graph.nodeColor(graph.nodeColor()).linkColor(graph.linkColor()).linkWidth(graph.linkWidth());
        for(const n of data.nodes)if(n.labelSprite){n.labelSprite.visible=!focus||near.has(n.id);n.labelSprite.color=n.id===focus?'#563775':'#25344e';}
      },
      fit() {graph.zoomToFit(450,65);},
      destroy() {
        disposed=true;host.removeEventListener('pointerdown',interaction);host.removeEventListener('wheel',interaction);clearTimeout(timer);observer.disconnect();document.removeEventListener('visibilitychange',visibility);
        graph._destructor();
      }
    };
  }
};
