import { useEffect, useState } from "react";
import { ClaimPage } from "./ClaimPage";
import { Instructions } from "./Instructions";
import { Queue } from "./Queue";

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => {
      setHash(window.location.hash);
    };
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return hash;
}

export function App() {
  const hash = useHash();
  const onInstructions = hash === "#/instructions";
  const claimId = /^#\/claims\/([\w-]+)$/.exec(hash)?.[1];

  return (
    <div className="shell">
      <header className="top">
        <a className="brand" href="#/">
          <strong>UnderCover</strong>
          <span className="tagline">Claims desk</span>
        </a>
        <nav className="nav">
          <a href="#/" aria-current={onInstructions ? undefined : "page"}>
            Queue
          </a>
          <a
            href="#/instructions"
            aria-current={onInstructions ? "page" : undefined}
          >
            Agent instructions
          </a>
        </nav>
      </header>
      <main>
        {onInstructions && <Instructions />}
        {claimId && <ClaimPage key={claimId} claimId={claimId} />}
        {!onInstructions && !claimId && <Queue />}
      </main>
    </div>
  );
}
