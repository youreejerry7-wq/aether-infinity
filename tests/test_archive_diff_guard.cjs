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

const ARCHIVE_PATHS = ["data/research.json", "data/research-latest.json"];

function archiveDiffExitCode(repo, baseSha, headSha) {
  // Compare the two trees directly. Three-dot syntax ignores base-only updates
  // when a PR branch is stale and can therefore allow an old archive to win.
  const result = spawnSync(
    "git",
    ["diff", "--quiet", baseSha, headSha, "--", ...ARCHIVE_PATHS],
    { cwd: repo }
  );
  if (result.error) throw result.error;
  return result.status;
}

test("stale PR archives are rejected until the branch matches the current base", () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "aether-archive-guard-"));
  try {
    git(repo, "init", "-q");
    git(repo, "branch", "-M", "main");
    git(repo, "config", "user.name", "AETHER test");
    git(repo, "config", "user.email", "aether-test@example.invalid");
    write(repo, "data/research.json", "base archive\n");
    write(repo, "data/research-latest.json", "base latest snapshot\n");
    commit(repo, "base archive");

    git(repo, "switch", "-c", "review/pr");
    write(repo, "cdn-preview/index.html", "preview\n");
    const stalePrHead = commit(repo, "preview-only change");

    git(repo, "switch", "main");
    write(repo, "data/research.json", "new scheduled cycle\n");
    write(repo, "data/research-latest.json", "new scheduled snapshot\n");
    const currentBase = commit(repo, "scheduled archive update");

    // A stale PR must fail because merging it would replace newer generated data.
    assert.equal(archiveDiffExitCode(repo, currentBase, stalePrHead), 1);

    // Once the PR branch incorporates the current base, the archive guard passes.
    git(repo, "switch", "review/pr");
    git(repo, "merge", "--no-ff", "main", "-m", "sync current base branch");
    const syncedPrHead = git(repo, "rev-parse", "HEAD");
    assert.equal(archiveDiffExitCode(repo, currentBase, syncedPrHead), 0);
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});

test("a PR that edits either generated research file is still rejected", () => {
  for (const editedPath of ARCHIVE_PATHS) {
    const repo = fs.mkdtempSync(path.join(os.tmpdir(), "aether-archive-guard-"));
    try {
      git(repo, "init", "-q");
      git(repo, "branch", "-M", "main");
      git(repo, "config", "user.name", "AETHER test");
      git(repo, "config", "user.email", "aether-test@example.invalid");
      write(repo, "data/research.json", "base archive\n");
      write(repo, "data/research-latest.json", "base latest snapshot\n");
      const baseSha = commit(repo, "base archive and snapshot");

      git(repo, "switch", "-c", "review/pr");
      write(repo, editedPath, "PR edited generated data\n");
      const prHead = commit(repo, "unauthorized generated-data edit");

      assert.equal(archiveDiffExitCode(repo, baseSha, prHead), 1, editedPath);
    } finally {
      fs.rmSync(repo, { recursive: true, force: true });
    }
  }
});
