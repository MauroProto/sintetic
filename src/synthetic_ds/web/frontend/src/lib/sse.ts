import { useEffect } from "react";

type MessageHandler = (data: unknown) => void;

export function useEventSource(
  url: string | null,
  onMessage: MessageHandler,
  onOpen?: () => void,
  onError?: (error: Event) => void,
): void {
  useEffect(() => {
    if (!url) return;
    const source = new EventSource(url);
    source.onopen = () => onOpen?.();
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        onMessage(payload);
      } catch {
        // ignore malformed payloads
      }
    };
    source.onerror = (event) => {
      onError?.(event);
    };
    return () => {
      source.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);
}
