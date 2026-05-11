from __future__ import annotations

import pytest
from fastapi import HTTPException

from hirocli.admin_svelte.routes.chat_channels import list_chat_channel_messages


@pytest.mark.asyncio
async def test_list_chat_messages_rejects_too_many_message_pks() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await list_chat_channel_messages(
            3,
            "ws-1",
            message_pk=list(range(1, 18)),
        )

    assert exc_info.value.status_code == 400
    assert "message_pk is limited" in str(exc_info.value.detail)
