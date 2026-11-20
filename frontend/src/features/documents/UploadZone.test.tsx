import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  UploadZone,
  UploadQueueList,
  useUploadQueue,
  validateFile,
  MAX_UPLOAD_BYTES,
} from "./UploadZone";
import { api } from "../../lib/api";
import { deferred } from "../../test/utils";

vi.mock("../../lib/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../lib/api")>();
  return { ...mod, api: { ...mod.api, uploadDocument: vi.fn() } };
});

function makeFile(name: string, size = 100, type = "application/pdf"): File {
  return new File([new Uint8Array(size)], name, { type });
}

describe("validateFile", () => {
  it("accepts pdf, docx, txt", () => {
    expect(validateFile(makeFile("a.pdf"))).toBeNull();
    expect(validateFile(makeFile("b.docx"))).toBeNull();
    expect(validateFile(makeFile("c.txt", 10, "text/plain"))).toBeNull();
  });

  it("rejects unsupported extensions", () => {
    expect(validateFile(makeFile("evil.exe"))).toMatch(/not a supported/);
    expect(validateFile(makeFile("noext"))).toMatch(/not a supported/);
  });

  it("rejects files over 20MB", () => {
    const big = makeFile("big.pdf", MAX_UPLOAD_BYTES + 1);
    expect(validateFile(big)).toMatch(/20 MB/);
  });

  it("rejects empty files", () => {
    expect(validateFile(makeFile("empty.pdf", 0))).toMatch(/empty/);
  });
});

describe("UploadZone", () => {
  it("renders the drop area and browse button", () => {
    render(<UploadZone onFiles={vi.fn()} />);
    expect(screen.getByTestId("upload-zone")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /choose files/i }),
    ).toBeInTheDocument();
  });

  it("passes dropped files to onFiles", () => {
    const onFiles = vi.fn();
    const { container } = render(<UploadZone onFiles={onFiles} />);
    const zone = container.querySelector("[data-testid='upload-zone']")!;
    const file = makeFile("dropped.pdf");
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("ignores drops while disabled", () => {
    const onFiles = vi.fn();
    const { container } = render(<UploadZone onFiles={onFiles} disabled />);
    const zone = container.querySelector("[data-testid='upload-zone']")!;
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile("a.pdf")] } });
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("disables picker, browse button and drops while uploading", () => {
    const onFiles = vi.fn();
    const { container } = render(<UploadZone onFiles={onFiles} uploading />);
    expect(screen.getByLabelText("Choose files to upload")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /choose files/i }),
    ).toBeDisabled();
    const zone = container.querySelector("[data-testid='upload-zone']")!;
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile("a.pdf")] } });
    expect(onFiles).not.toHaveBeenCalled();
  });
});

type QueueApi = ReturnType<typeof useUploadQueue>;
const queueRef: { current: QueueApi | null } = { current: null };

function QueueHarness({ onUploaded = vi.fn() }: { onUploaded?: () => void }) {
  const q = useUploadQueue(onUploaded);
  queueRef.current = q;
  return (
    <div>
      <div data-testid="busy">{String(q.busy)}</div>
      <div data-testid="states">
        {q.items.map((i) => `${i.file.name}:${i.state}`).join("|")}
      </div>
      <UploadQueueList items={q.items} onDismiss={q.dismiss} disabled={q.busy} />
      <button onClick={() => q.clear()}>clear-report</button>
    </div>
  );
}

function enqueueFiles(files: File[], upload?: (f: File) => Promise<unknown>) {
  const q = queueRef.current;
  if (!q) throw new Error("queue not mounted");
  return q.enqueue(files, upload ?? ((f) => api.uploadDocument(f)));
}

async function flush() {
  await act(async () => {});
}

/** Let already-resolved promises run their continuations. */
async function flushMicrotasks() {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

describe("useUploadQueue", () => {
  beforeEach(() => {
    vi.mocked(api.uploadDocument).mockReset();
    queueRef.current = null;
  });

  it("uploads valid files and reports success", async () => {
    vi.mocked(api.uploadDocument).mockResolvedValue({ id: "d1" } as never);
    render(<QueueHarness />);
    await act(async () => {
      await enqueueFiles([makeFile("ok.pdf")]);
    });
    expect(screen.getByTestId("states")).toHaveTextContent("ok.pdf:done");
    expect(api.uploadDocument).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("busy")).toHaveTextContent("false");
  });

  it("surfaces validation errors without calling the API", async () => {
    render(<QueueHarness />);
    await act(async () => {
      await enqueueFiles([makeFile("bad.exe")]);
    });
    expect(screen.getByTestId("states")).toHaveTextContent("bad.exe:error");
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });

  it("surfaces server errors per file", async () => {
    vi.mocked(api.uploadDocument).mockRejectedValue(
      new Error("Document with this filename already exists"),
    );
    render(<QueueHarness />);
    await act(async () => {
      await enqueueFiles([makeFile("dup.pdf")]);
    });
    expect(screen.getByTestId("states")).toHaveTextContent("dup.pdf:error");
  });

  it("assigns stable unique ids to duplicate filenames", async () => {
    const d1 = deferred<unknown>();
    const d2 = deferred<unknown>();
    const upload = vi
      .fn()
      .mockImplementationOnce(() => d1.promise)
      .mockImplementationOnce(() => d2.promise);
    render(<QueueHarness />);

    let pending!: Promise<void>;
    await act(async () => {
      pending = enqueueFiles(
        [makeFile("same.pdf"), makeFile("same.pdf")],
        upload,
      );
      await flushMicrotasks();
    });

    // Both rows render despite identical names.
    expect(screen.getAllByText("same.pdf")).toHaveLength(2);
    expect(screen.getByTestId("states")).toHaveTextContent(
      "same.pdf:uploading|same.pdf:queued",
    );

    await act(async () => {
      d1.resolve({});
      await flush();
    });
    expect(screen.getByTestId("states")).toHaveTextContent(
      "same.pdf:done|same.pdf:uploading",
    );

    await act(async () => {
      d2.resolve({});
      await pending;
    });
    expect(screen.getByTestId("states")).toHaveTextContent(
      "same.pdf:done|same.pdf:done",
    );

    // Dismissing the first row must not remove the second.
    const dismissButtons = screen.getAllByRole("button", {
      name: "Dismiss same.pdf",
    });
    await userEvent.click(dismissButtons[0]);
    expect(screen.getAllByText("same.pdf")).toHaveLength(1);
  });

  it("rejects a concurrent enqueue while busy", async () => {
    const d = deferred<unknown>();
    render(<QueueHarness />);
    await act(async () => {
      void enqueueFiles([makeFile("first.pdf")], () => d.promise);
      await flushMicrotasks();
    });
    expect(screen.getByTestId("busy")).toHaveTextContent("true");

    await act(async () => {
      await enqueueFiles([makeFile("second.pdf")], vi.fn());
    });
    // Second batch was ignored entirely.
    expect(screen.getByTestId("states")).toHaveTextContent("first.pdf:uploading");
    expect(screen.queryByText("second.pdf")).not.toBeInTheDocument();

    await act(async () => {
      d.resolve({});
      await flush();
    });
  });

  it("blocks clear while an upload is in flight", async () => {
    const user = userEvent.setup();
    const d = deferred<unknown>();
    render(<QueueHarness />);
    await act(async () => {
      void enqueueFiles([makeFile("a.pdf")], () => d.promise);
      await flushMicrotasks();
    });
    await user.click(screen.getByText("clear-report"));
    expect(screen.getByTestId("states")).toHaveTextContent("a.pdf:uploading");
    await act(async () => {
      d.resolve({});
      await flush();
    });
    await user.click(screen.getByText("clear-report"));
    expect(screen.getByTestId("states")).toHaveTextContent("");
  });

  it("blocks dismiss while an upload is in flight", async () => {
    const user = userEvent.setup();
    const d = deferred<unknown>();
    const upload = vi
      .fn()
      .mockResolvedValueOnce({})
      .mockImplementationOnce(() => d.promise);
    render(<QueueHarness />);
    await act(async () => {
      void enqueueFiles(
        [makeFile("done.pdf"), makeFile("pending.pdf")],
        upload,
      );
      await flushMicrotasks();
    });
    // done.pdf finished; pending.pdf is still uploading.
    expect(screen.getByTestId("states")).toHaveTextContent(
      "done.pdf:done|pending.pdf:uploading",
    );
    const dismissDone = screen.getByRole("button", {
      name: "Dismiss done.pdf",
    });
    expect(dismissDone).toBeDisabled();
    await user.click(dismissDone);
    expect(screen.getAllByText("done.pdf")).toHaveLength(1);

    await act(async () => {
      d.resolve({});
      await flush();
    });
    expect(
      screen.getByRole("button", { name: "Dismiss done.pdf" }),
    ).toBeEnabled();
    await user.click(
      screen.getByRole("button", { name: "Dismiss done.pdf" }),
    );
    expect(screen.queryByText("done.pdf")).not.toBeInTheDocument();
  });

  it("resets busy state when the completion callback throws", async () => {
    const onUploaded = vi
      .fn()
      .mockImplementationOnce(() => {
        throw new Error("callback failed");
      });
    render(<QueueHarness onUploaded={onUploaded} />);
    await act(async () => {
      await expect(
        enqueueFiles([makeFile("ok.pdf")], async () => ({})),
      ).rejects.toThrow("callback failed");
    });
    expect(screen.getByTestId("busy")).toHaveTextContent("false");
    // Queue is usable again.
    await act(async () => {
      await enqueueFiles([makeFile("again.pdf")], async () => ({}));
    });
    expect(screen.getByTestId("states")).toHaveTextContent("again.pdf:done");
  });

  it("ignores empty file arrays", async () => {
    const onUploaded = vi.fn();
    render(<QueueHarness onUploaded={onUploaded} />);
    await act(async () => {
      await enqueueFiles([]);
    });
    expect(onUploaded).not.toHaveBeenCalled();
    expect(screen.getByTestId("busy")).toHaveTextContent("false");
  });
});
