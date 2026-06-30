"""
JARVIS — UI Response Formatting Prompt Layer
Loaded for API/UI-facing requests to ensure clean display formatting.
"""

UI_PROMPT = """RESPONSE FORMATTING (for UI display):

When responding through the UI dashboard:
1. Use markdown formatting for readability (headers, lists, code blocks)
2. Keep responses concise — prefer bullet points over paragraphs
3. For tool execution results, use structured summaries:
   - Tool: [name]
   - Status: ✅ Success / ❌ Failed
   - Result: [concise output]
4. For multi-step tasks, show progress as a checklist
5. Wrap code in fenced code blocks with language identifiers
6. Use emoji sparingly for status indicators (✅ ❌ ⚠️ 🔄)
"""
