import { copyText, downloadSvgAsPng, downloadTextFile } from "./export-utils";

describe("downloadTextFile", () => {
  it("creates an object URL, triggers a download, and revokes the URL", () => {
    const createObjectURL = jest.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURL = jest.fn();
    global.URL.createObjectURL = createObjectURL;
    global.URL.revokeObjectURL = revokeObjectURL;

    const clickSpy = jest.fn();
    const realCreateElement = document.createElement.bind(document);
    jest.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") el.click = clickSpy;
      return el;
    });

    downloadTextFile("hello world", "report.md", "text/markdown");

    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");

    (document.createElement as jest.Mock).mockRestore();
  });
});

describe("copyText", () => {
  it("returns true on success", async () => {
    Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });
    await expect(copyText("hello")).resolves.toBe(true);
  });

  it("returns false instead of throwing when clipboard access is denied", async () => {
    Object.assign(navigator, { clipboard: { writeText: jest.fn().mockRejectedValue(new Error("denied")) } });
    await expect(copyText("hello")).resolves.toBe(false);
  });
});

describe("downloadSvgAsPng", () => {
  let originalImage: typeof Image;

  beforeEach(() => {
    originalImage = global.Image;
    global.URL.createObjectURL = jest.fn().mockReturnValue("blob:svg-url");
    global.URL.revokeObjectURL = jest.fn();
  });

  afterEach(() => {
    global.Image = originalImage;
  });

  it("rasterizes the SVG to a PNG download", async () => {
    class MockImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_value: string) {
        // Simulate the browser's async image decode completing successfully.
        setTimeout(() => this.onload?.(), 0);
      }
    }
    global.Image = MockImage as unknown as typeof Image;

    const toBlobMock = jest.fn((cb: (blob: Blob | null) => void) => cb(new Blob(["fake-png"])));
    const getContextMock = jest.fn().mockReturnValue({ fillStyle: "", fillRect: jest.fn(), drawImage: jest.fn() });
    jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(getContextMock as any);
    jest.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(toBlobMock as any);

    const clickSpy = jest.fn();
    const realCreateElement = document.createElement.bind(document);
    jest.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") el.click = clickSpy;
      return el;
    });

    await downloadSvgAsPng('<svg width="400" height="300"><rect /></svg>', "diagram.png");

    expect(clickSpy).toHaveBeenCalled();

    (document.createElement as jest.Mock).mockRestore();
    (HTMLCanvasElement.prototype.getContext as jest.Mock).mockRestore();
    (HTMLCanvasElement.prototype.toBlob as jest.Mock).mockRestore();
  });

  it("rejects when the image fails to load", async () => {
    class MockFailingImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_value: string) {
        setTimeout(() => this.onerror?.(), 0);
      }
    }
    global.Image = MockFailingImage as unknown as typeof Image;

    await expect(downloadSvgAsPng("<svg></svg>", "diagram.png")).rejects.toThrow();
  });
});
