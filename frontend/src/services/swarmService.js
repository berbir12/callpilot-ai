/**
 * Service for connecting to the swarm streaming API
 * Handles NDJSON parsing and event callbacks
 */

export const startSwarm = async (payload, callbacks) => {
  const { onStart, onProgress, onComplete, onError } = callbacks;

  try {
    const response = await fetch('/swarm/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (body && typeof body.error === 'string') message = body.error;
      } catch {
        // ignore
      }
      const err = new Error(message);
      err.status = response.status;
      throw err;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      
      // Keep the last incomplete line in buffer
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.trim()) {
          try {
            const event = JSON.parse(line);
            
            switch (event.type) {
              case 'start':
                onStart?.(event);
                break;
              case 'progress':
                onProgress?.(event.result);
                break;
              case 'complete':
                onComplete?.(event);
                break;
              default:
                console.warn('Unknown event type:', event.type);
            }
          } catch (e) {
            console.error('Failed to parse event:', line, e);
          }
        }
      }
    }

    // Process any remaining buffer
    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer);
        if (event.type === 'complete') {
          onComplete?.(event);
        }
      } catch (e) {
        console.error('Failed to parse final event:', buffer, e);
      }
    }
  } catch (error) {
    console.error('Swarm service error:', error);
    onError?.(error);
    throw error;
  }
};
