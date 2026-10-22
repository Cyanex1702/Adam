import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { AvatarState, Preferences } from "./state";
import { stateCopy } from "./state";

const colors: Record<AvatarState, number> = {
  LISTENING: 0x8ac7aa,
  SPEAKING: 0x9ca9db,
  IDLE: 0x52b7a7,
  UNDERSTANDING: 0x83c5ba,
  THINKING: 0x7c9cdd,
  SEARCHING: 0x52b7a7,
  USING_TOOL: 0xc1a257,
  WAITING_FOR_PERMISSION: 0xd9a557,
  UNCERTAIN: 0x6eaaa1,
  ERROR: 0xe28270,
  OFFLINE: 0x82908e,
};
export function Avatar({
  state,
  preferences,
  audioEnergy = 0,
}: {
  state: AvatarState;
  preferences: Preferences;
  audioEnergy?: number;
}) {
  const host = useRef<HTMLDivElement>(null),
    current = useRef(state);
  current.current = state;
  const actualEnergy = useRef(audioEnergy);
  actualEnergy.current = audioEnergy;
  const [fps, setFps] = useState<number | null>(null),
    [simple, setSimple] = useState(false);
  useEffect(() => {
    const target = host.current;
    if (!target || !preferences.avatar) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: false,
        powerPreference: "low-power",
      });
    } catch {
      setSimple(true);
      return;
    }
    setSimple(false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.25));
    renderer.setSize(256, 256);
    target.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-hidden", "true");
    const scene = new THREE.Scene(),
      camera = new THREE.PerspectiveCamera(40, 1, 0.1, 10);
    camera.position.z = 3.6;
    const uniforms = {
      time: { value: 0 },
      tone: { value: new THREE.Color(colors[current.current]) },
      energy: { value: 0.12 },
    };
    const material = new THREE.ShaderMaterial({
      uniforms,
      transparent: true,
      vertexShader: `uniform float time;uniform float energy;varying vec3 p;varying vec3 n;void main(){p=position;n=normal;float ripple=sin(position.y*6.+time*.8)*sin(position.x*5.-time*.5)*energy;gl_Position=projectionMatrix*modelViewMatrix*vec4(position+normal*ripple,1.);}`,
      fragmentShader: `uniform float time;uniform vec3 tone;varying vec3 p;varying vec3 n;void main(){float rim=pow(1.-abs(n.z),2.);float band=.5+.5*sin(p.y*17.+sin(p.x*8.+time*.25)+time*.5);float light=.3+max(dot(normalize(n),normalize(vec3(-.7,.8,1.))),0.)*.5;vec3 color=mix(tone*.2,tone,light)+vec3(.35,.45,.43)*rim;float weave=smoothstep(.4,.65,band)*.12;gl_FragColor=vec4(color+weave,.96);}`,
    });
    const geometry = new THREE.SphereGeometry(0.86, 48, 32),
      mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    let frame = 0,
      frames = 0,
      started = performance.now(),
      last = started,
      elapsed = 0,
      disposed = false;
    function render(now: number) {
      if (disposed || document.hidden) return;
      elapsed += Math.min((now - last) / 1000, 0.1);
      last = now;
      uniforms.time.value = preferences.reducedMotion ? 0 : elapsed;
      uniforms.tone.value.set(colors[current.current]);
      uniforms.energy.value = ["THINKING", "SEARCHING", "USING_TOOL"].includes(
        current.current,
      )
        ? 0.2
        : current.current === "SPEAKING"
          ? Math.min(0.3, actualEnergy.current * 2)
          : 0.07;
      mesh.rotation.y = preferences.reducedMotion ? 0 : elapsed * 0.08;
      renderer.render(scene, camera);
      frames++;
      if (now - started >= 2000) {
        setFps(Math.round((frames * 1000) / (now - started)));
        frames = 0;
        started = now;
      }
      if (!preferences.reducedMotion) frame = requestAnimationFrame(render);
    }
    const visibility = () => {
      cancelAnimationFrame(frame);
      last = started = performance.now();
      frames = 0;
      if (!document.hidden) frame = requestAnimationFrame(render);
    };
    const stateChange = () => {
      if (preferences.reducedMotion && !document.hidden)
        render(performance.now());
    };
    frame = requestAnimationFrame(render);
    document.addEventListener("visibilitychange", visibility);
    target.addEventListener("statechange", stateChange);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", visibility);
      target.removeEventListener("statechange", stateChange);
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [preferences.avatar, preferences.reducedMotion]);
  // Static reduced-motion rendering still changes color when a real state changes.
  useEffect(() => {
    if (preferences.reducedMotion)
      host.current?.dispatchEvent(new Event("statechange"));
  }, [state, preferences.reducedMotion]);
  return (
    <section className="avatar-panel" aria-label="System state">
      <div className="eyebrow">
        SYSTEM STATE <span className="live-dot" />
      </div>
      <div className="orb-stage">
        <div ref={host} className="orb-canvas" />
        {preferences.avatar && simple && (
          <div className={"simple-orb " + state.toLowerCase()} />
        )}
        <div className="orbit orbit-one" />
        <div className="orbit orbit-two" />
      </div>
      <div className="state-caption" aria-live="polite">
        <span className={"state-mark " + state.toLowerCase()} />
        <h2>{stateCopy[state][0]}</h2>
        <p>{stateCopy[state][1]}</p>
      </div>
      <div className="render-note">
        {!preferences.avatar
          ? "Avatar hidden"
          : simple
            ? "Simple rendering"
            : preferences.reducedMotion
              ? "Static · reduced motion"
              : fps
                ? `${fps} FPS · local rendering`
                : "Measuring rendering…"}
      </div>
      <div className="avatar-note">
        An abstract view of system activity.
        <br />
        No emotion or human presence implied.
      </div>
    </section>
  );
}
