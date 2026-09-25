import { useEffect } from "react";
import { useWorldStream } from "./api/stream";
import { Board } from "./board/Board";
import { installUiSounds } from "./sfx";
import { useStore } from "./store";
import { Controls, EmptyHint, RunCapsule, Toast, WorldPill } from "./ui/Chrome";
import { Inspector } from "./ui/Inspector";
import { PromptModal } from "./ui/PromptModal";

export function App() {
  const world = useStore((s) => s.world);
  useEffect(() => {
    void useStore.getState().init();
    return installUiSounds();
  }, []);
  useWorldStream(world?.id);

  return (
    <div className="app">
      <Board />
      <WorldPill />
      <Controls />
      <EmptyHint />
      <RunCapsule />
      <Toast />
      <Inspector />
      <PromptModal />
    </div>
  );
}
