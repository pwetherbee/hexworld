import { useEffect } from "react";
import { useWorldStream } from "./api/stream";
import { Board } from "./board/Board";
import { installUiSounds } from "./sfx";
import { useStore } from "./store";
import { Controls, EmptyHint, RunCapsule, Toast, WorldPill } from "./ui/Chrome";
import { Inspector } from "./ui/Inspector";
import { GamePill, PlayHud, SceneView } from "./ui/Play";
import { usePlay } from "./play";
import { PromptModal } from "./ui/PromptModal";

export function App() {
  const world = useStore((s) => s.world);
  const playing = usePlay((s) => s.active);
  useEffect(() => {
    void useStore.getState().init();
    return installUiSounds();
  }, []);
  useWorldStream(world?.id);

  return (
    <div className="app">
      <Board />
      {!playing && <WorldPill />}
      <GamePill />
      <Controls />
      {!playing && <EmptyHint />}
      {!playing && <RunCapsule />}
      <Toast />
      {!playing && <Inspector />}
      {!playing && <PromptModal />}
      <PlayHud />
      <SceneView />
    </div>
  );
}
