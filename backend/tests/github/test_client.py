from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.github.auth import GitHubAuth
from app.github.client import GitHubClient

@pytest.fixture
def mock_httpx_client():
    with patch("app.github.client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        async def mock_request(method, url, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 200
            
            if "git/ref/heads" in url and method == "GET":
                mock_response.json.return_value = {"object": {"sha": "head-sha"}}
            elif "git/commits" in url and method == "GET":
                mock_response.json.return_value = {"tree": {"sha": "base-tree-sha"}}
            elif "git/blobs" in url:
                mock_response.json.return_value = {"sha": "blob-sha"}
            elif "git/trees" in url:
                mock_response.json.return_value = {"sha": "new-tree-sha"}
            elif "git/commits" in url and method == "POST":
                mock_response.json.return_value = {"sha": "new-commit-sha"}
            elif "git/refs/heads" in url and method == "PATCH":
                mock_response.json.return_value = {}
            
            # This allows inspecting the calls
            return mock_response
            
        mock_client.request.side_effect = mock_request
        yield mock_client


@pytest.mark.asyncio
async def test_push_files_delta(mock_httpx_client):
    auth = GitHubAuth(mode="token", token="fake")
    client = GitHubClient(auth)

    await client.push_files(
        "owner", "repo", "main-branch",
        [{"path": "file1.txt", "content": "hello"}],
        commit_message="test",
        authoritative=False
    )
    
    # Check that in the calls, the tree post had base_tree_sha
    tree_calls = [call for call in mock_httpx_client.request.call_args_list if "git/trees" in call.args[1]]
    assert len(tree_calls) == 1
    tree_body = tree_calls[0].kwargs.get("json")
    
    assert tree_body is not None
    assert tree_body.get("base_tree") == "base-tree-sha"
    assert "tree" in tree_body
    assert len(tree_body["tree"]) == 1


@pytest.mark.asyncio
async def test_push_files_authoritative(mock_httpx_client):
    auth = GitHubAuth(mode="token", token="fake")
    client = GitHubClient(auth)

    await client.push_files(
        "owner", "repo", "main-branch",
        [{"path": "file1.txt", "content": "hello"}],
        commit_message="test",
        authoritative=True
    )
    
    # Check that in the calls, the tree post DID NOT have base_tree_sha
    tree_calls = [call for call in mock_httpx_client.request.call_args_list if "git/trees" in call.args[1]]
    assert len(tree_calls) == 1
    tree_body = tree_calls[0].kwargs.get("json")
    
    assert tree_body is not None
    assert "base_tree" not in tree_body
    assert "tree" in tree_body
    assert len(tree_body["tree"]) == 1
