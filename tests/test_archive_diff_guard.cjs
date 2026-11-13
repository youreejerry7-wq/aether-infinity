const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync, spawnSync } = require("node:child_process");
const test = require("node:test");

function git(repo, ...args) {
  return execFileSync("git", args, { cwd: repo, encoding: "utf8" }).trim();
}

function write(repo, relative, content) {
  const target = path.join(repo, relative);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
}

function commit(repo, message) {
  git(repo, "add", "--all");
  git(repo, "commit", "-m", message);
  return git(repo, "rev-parse", "HEAD");
}

function archiveDiffExitCode(repo, baseSha, headSha) {
  const result = spawnSync(
    "git",
    ["diff", "--quiet", `${baseSha}...${headSha}`, "--", "data/research.json"],
    { cwd: repo }
  );
  if (result.error) throw result.error;
  return result.status;
}

test("base-branch archive advances do not look like PR archive edits", () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "aether-archive-guard-"));
  try {
    git(repo, "init", "-q");
    git(repo, "branch", "-M", "main");
    git(repo, "config", "user.name", "AETHER test");
    git(repo, "config", "user.email", "aether-test@example.invalid");
    write(repo, "data/research.json", "base archive\\n");
    const baseSha = commit(repo, "base archive");

    git(repo, "switch", "-c", "review/pr");
    write(repo, "cdn-preview/index.html", "preview\\n");
    const prHead = commit(repo, "preview-only change");

    git(repo, "switch", "main");
    write(repo, "data/research.json", "new scheduled cycle\\n");
    const currentBase = commit(repo, "scheduled archive update");

    // Mirror a review-branch sync: the PR head contains the current base
    // branch, while the PR event's captured base SHA can still be stale.
    git(repo, "switch", "review/pr");
    git(repo, "merge", "--no-ff", "main", "-m", "sync current base branch");
    const syncedPrHead = git(repo, "rev-parse", "HEAD");

    assert.equal(archiveDiffExitCode(repo, currentBase, syncedPrHead), 0);
    // The old event base would falsely attribute the base branch's archive
    // update to the PR, which is why CI must compare against current origin/main.
    assert.equal(archiveDiffExitCode(repo, baseSha, syncedPrHead), 1);
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test("a PR that edits the archive is still rejected", () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "aether-archive-guard-"));
  try {
    git(repo, "init", "-q");
    git(repo, "branch", "-M", "main");
    git(repo, "config", "user.name", "AETHER test");
    git(repo, "config", "user.email", "aether-test@example.invalid");
    write(repo, "data/research.json", "base archive\\n");
    const baseSha = commit(repo, "base archive");

    git(repo, "switch", "-c", "review/pr");
    write(repo, "data/research.json", "PR edited archive\\n");
    const prHead = commit(repo, "unauthorized archive edit");

    assert.equal(archiveDiffExitCode(repo, baseSha, prHead), 1);
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});
