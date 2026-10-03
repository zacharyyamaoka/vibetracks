// Type stand-ins for the roadmap's unit tests under this package's tsc. WHY: the package installs no node_modules
// (tsconfig.json borrows Clank's react and @clank/api by path), so tsc cannot see vitest or Node's types, while the
// tests run under clank-kinsim's vitest binary, which supplies the real modules. Only what the tests call is declared.

declare module 'vitest' {
  interface Matchers {
    toBe(expected: unknown): void
    toEqual(expected: unknown): void
    toContainEqual(expected: unknown): void
    toMatch(expected: RegExp | string): void
    toThrow(expected?: RegExp | string): void
    toBeNull(): void
    toBeGreaterThan(expected: number): void
    toBeGreaterThanOrEqual(expected: number): void
    toBeLessThan(expected: number): void
    toBeLessThanOrEqual(expected: number): void
    toHaveLength(expected: number): void
    not: Matchers
  }
  export function describe(name: string, body: () => void): void
  export function it(name: string, body: () => void | Promise<void>): void
  export function expect(actual: unknown, message?: string): Matchers
}

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string
}
