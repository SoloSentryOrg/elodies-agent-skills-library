#!/usr/bin/env ruby
# frozen_string_literal: true

require "pathname"
require "yaml"

ROOT = Pathname.new(__dir__).parent.cleanpath
errors = []

forbidden_names = [".DS_Store", ".env", "id_rsa", "id_ed25519"]
secret_patterns = {
  "GitHub token" => /\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/,
  "AWS access key" => /\bAKIA[0-9A-Z]{16}\b/,
  "private key" => /-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----/
}.freeze
ROOT.find do |path|
  next if path.directory? || path.to_s.include?("/.git/")

  relative = path.relative_path_from(ROOT).to_s
  basename = path.basename.to_s
  errors << "forbidden file: #{relative}" if forbidden_names.include?(basename)

  begin
    content = path.binread
    if content.valid_encoding?
      secret_patterns.each do |label, pattern|
        errors << "possible #{label}: #{relative}" if content.match?(pattern)
      end
    end
  rescue Errno::EACCES
    errors << "unreadable file: #{relative}"
  end

  if relative.start_with?(".github/workflows/")
    path.each_line.with_index(1) do |line, number|
      next unless line.match?(/^\s*(?:-\s*)?uses:\s*/)
      next if line.match?(/uses:\s*\.\//)
      next if line.match?(/@[0-9a-fA-F]{40}(?:\s|#|$)/)

      errors << "unpinned action: #{relative}:#{number}"
    end
  end
end

reserved = %w[.git .github scripts]
skill_roots = ROOT.children.select do |path|
  path.directory? && !reserved.include?(path.basename.to_s) && path.join("SKILL.md").file?
end.sort
errors << "no skills found" if skill_roots.empty?

ROOT.children.select(&:directory?).each do |path|
  next if reserved.include?(path.basename.to_s) || path.join("SKILL.md").file?

  errors << "unexpected root directory without SKILL.md: #{path.basename}"
end

skill_roots.each do |skill_root|
  skill_file = skill_root.join("SKILL.md")
  unless skill_file.file?
    errors << "missing SKILL.md: #{skill_root.relative_path_from(ROOT)}"
    next
  end

  text = skill_file.read
  match = text.match(/\A---\s*\n(.*?)\n---\s*\n/m)
  unless match
    errors << "invalid frontmatter delimiters: #{skill_file.relative_path_from(ROOT)}"
    next
  end

  begin
    metadata = YAML.safe_load(match[1], permitted_classes: [], aliases: false)
  rescue Psych::Exception => e
    errors << "invalid YAML: #{skill_file.relative_path_from(ROOT)}: #{e.message}"
    next
  end

  unless metadata.is_a?(Hash) && metadata.keys.sort == %w[description metadata name]
    errors << "frontmatter must contain name, description, and metadata: #{skill_file.relative_path_from(ROOT)}"
    next
  end

  expected_name = skill_root.basename.to_s
  errors << "skill name mismatch: #{expected_name}" unless metadata["name"] == expected_name
  errors << "invalid skill name: #{expected_name}" unless expected_name.match?(/\A[a-z0-9]+(?:-[a-z0-9]+)*\z/) && expected_name.length < 64
  errors << "empty description: #{expected_name}" unless metadata["description"].is_a?(String) && !metadata["description"].strip.empty?
  skill_metadata = metadata["metadata"]
  unless skill_metadata.is_a?(Hash) && skill_metadata.all? { |key, value| key.is_a?(String) && value.is_a?(String) }
    errors << "metadata must be a string-to-string mapping: #{expected_name}"
  else
    version = skill_metadata["version"]
    unless version.is_a?(String) && version.match?(/\A(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\z/)
      errors << "metadata.version must be a quoted semantic version: #{expected_name}"
    end
  end

  text.scan(/\]\((references\/[^)]+)\)/).flatten.each do |reference|
    errors << "missing reference: #{expected_name}/#{reference}" unless skill_root.join(reference).file?
  end

  ui_file = skill_root.join("agents/openai.yaml")
  next unless ui_file.file?

  begin
    ui = YAML.safe_load(ui_file.read, permitted_classes: [], aliases: false)
    prompt = ui.dig("interface", "default_prompt")
    errors << "default prompt must invoke $#{expected_name}: #{expected_name}" unless prompt.is_a?(String) && prompt.include?("$#{expected_name}")
  rescue Psych::Exception => e
    errors << "invalid UI YAML: #{ui_file.relative_path_from(ROOT)}: #{e.message}"
  end
end

if errors.any?
  warn errors.map { |error| "ERROR: #{error}" }.join("\n")
  exit 1
end

puts "Repository validation passed for #{skill_roots.length} skill(s)."
