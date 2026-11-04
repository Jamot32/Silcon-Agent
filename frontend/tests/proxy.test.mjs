import assert from "node:assert/strict";
import test from "node:test";
import { config, proxy } from "../proxy.ts";

const request = (host) => new Request("http://localhost:3000/api/runs", { headers: host === null ? {} : { host } });

test("API proxy passes loopback hosts and rejects DNS-rebinding names", async () => {
  assert.equal(config.matcher, "/api/:path*");
  for (const host of ["localhost:3000", "LOCALHOST:3000", "127.0.0.1:3000", "localhost"]) assert.equal(proxy(request(host)), undefined, host);
  for (const host of ["evil.example", "evil.example:3000", "localhost.evil.example:3000", "localhost@evil.example", "api:8000", "[::1]:3000", null]) {
    const response = proxy(request(host));
    assert.equal(response?.status, 400, String(host));
    assert.deepEqual(await response.json(), { detail: "Invalid host header" });
  }
});
