def test_build_chunk_prompts_with_template_context():
    from app.llm.prompts.code_generation import build_chunk_prompts
    
    template_context = {
        "inventory": ["package.json", "app/page.tsx", "app/layout.tsx"],
        "files": {
            "package.json": "{\"name\": \"test\"}"
        }
    }
    
    system_prompt, user_prompt = build_chunk_prompts(
        chunk="shared_foundation",
        template_context=template_context
    )
    
    # Check system prompt assertions
    assert "package_changes" in system_prompt
    assert "DO NOT EVER output a replacement `package.json` file" in system_prompt
    
    # Check user prompt assertions
    assert "packager additions for the **shared_foundation** phase" in user_prompt or "package additions for the **shared_foundation** phase" in user_prompt
    assert "### Template Inventory" in user_prompt
    assert "- package.json" in user_prompt
    assert "### Template Key Files" in user_prompt
    assert "#### package.json\n```\n{\"name\": \"test\"}\n```" in user_prompt
    
    # Check chunk constraints
    assert "reusable UI components in `components/`" in user_prompt
    assert "`src/components/`" not in user_prompt
    assert "`src/data/`" not in user_prompt


def test_pages_prompt_uses_root_app_router_paths():
    from app.llm.prompts.code_generation import build_chunk_prompts

    _, user_prompt = build_chunk_prompts(chunk="pages", template_context={"inventory": [], "files": {}})

    assert "root `app/page.tsx`" in user_prompt
    assert "`src/app/page.tsx`" not in user_prompt
