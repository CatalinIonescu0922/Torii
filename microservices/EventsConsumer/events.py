"""
Layer C: Logic Layer - Event Router and Handlers
Routes and processes Gerrit events
"""
import logging
from typing import Union, Optional
import sys
sys.path.append('..')

from shared.model import (
    PatchSetCreatedEvent,
    CommentAddedEvent,
    ChangeMergedEvent,
    DraftPublishedEvent,
    RoutingDecision,
    Approval
)

logger = logging.getLogger(__name__)



class Config:
    """Centralized configuration for event handling logic"""
    
    # Projects to monitor (empty list = monitor all)
    MONITORED_PROJECTS: list[str] = []
    
    # Ignored patterns
    IGNORE_WIP_CHANGES = True
    IGNORE_PRIVATE_CHANGES = True
    IGNORED_AUTHORS: list[str] = ["jenkins@company.com", "ci-bot@company.com"]
    IGNORE_REF_UPDATED_EVENTS = True



def route_event(event: Union[PatchSetCreatedEvent, CommentAddedEvent, ChangeMergedEvent, DraftPublishedEvent]) -> RoutingDecision:
    """
    Routes validated events to the appropriate handler.
    
    Args:
        event: Validated Pydantic event model
        
    Returns:
        RoutingDecision with action
    """
    handler_map = {
        "patchset-created": handle_patchset_created,
        "comment-added": handle_comment_added,
        "change-merged": handle_change_merged,
        "draft-published": handle_draft_published,
    }
    
    handler = handler_map.get(event.type)
    
    if handler:
        logger.info(f"Routing {event.type} event for project: {event.change.project}")
        return handler(event)
    else:
        logger.warning(f"Unknown event type: {event.type}")
        return RoutingDecision(
            action="IGNORE",
            reason=f"Unknown event type: {event.type}"
        )


def handle_patchset_created(event: PatchSetCreatedEvent) -> RoutingDecision:
    """
    Handles patchset created events.
    
    Filters:
    - WIP changes
    - Private changes
    - Non-monitored projects
    - Ignored authors
    """
    change = event.change
    
    # Filter: WIP changes
    if Config.IGNORE_WIP_CHANGES and change.wip:
        return RoutingDecision(
            action="IGNORE",
            reason=f"WIP change in {change.project}"
        )
    
    # Filter: Private changes
    if Config.IGNORE_PRIVATE_CHANGES and change.private:
        return RoutingDecision(
            action="IGNORE",
            reason=f"Private change in {change.project}"
        )
    
    # Filter: Monitored projects
    if Config.MONITORED_PROJECTS and change.project not in Config.MONITORED_PROJECTS:
        return RoutingDecision(
            action="IGNORE",
            reason=f"Project {change.project} not in monitored list"
        )
    
    # Filter: Ignored authors
    if event.uploader.email in Config.IGNORED_AUTHORS:
        return RoutingDecision(
            action="IGNORE",
            reason=f"Author {event.uploader.email} is ignored"
        )

    logger.info(f"✓ Processing patchset for {change.project}")
    return RoutingDecision(action="PROCESS", reason="New patchset uploaded")

def handle_comment_added(event: CommentAddedEvent) -> RoutingDecision:
    """
    Handles comment added events with review labels.
    
    Decision Logic:
    - Processes review labels (Verified, Code-Review)
    - Logs approval information
    """
    change = event.change
    approvals = event.approvals or []
    
    if not approvals:
        return RoutingDecision(
            action="IGNORE",
            reason="No approvals in comment"
        )
    
    # Analyze labels
    label_info = []
    for approval in approvals:
        label_type = approval.type
        value = approval.value
        label_info.append(f"{label_type}: {value}")
    
    labels_str = ", ".join(label_info)
    logger.info(f"✓ Processing comment for {change.project} (labels: {labels_str})")
    return RoutingDecision(action="PROCESS", reason=f"Labels: {labels_str}")


# ============================================================================
# HANDLER: CHANGE-MERGED
# ============================================================================

def handle_change_merged(event: ChangeMergedEvent) -> RoutingDecision:
    """
    Handles post-merge events.
    
    Processes merged changes on protected branches.
    """
    change = event.change
    
    # Filter: Only process protected branches
    protected_branches = ["master", "main", "develop"]
    is_protected = any(change.branch == branch or change.branch.startswith("release/") 
                      for branch in protected_branches)
    
    if not is_protected:
        return RoutingDecision(
            action="IGNORE",
            reason=f"Branch {change.branch} is not protected"
        )
    
    logger.info(f"✓ Processing merge for {change.project} on {change.branch}")
    return RoutingDecision(action="PROCESS", reason=f"Merged to {change.branch}")



def handle_draft_published(event: DraftPublishedEvent) -> RoutingDecision:
    """
    Handles draft publication events.
    
    Typically treated similar to patchset-created.
    """
    change = event.change
    patchset = event.patchSet
    
    # Reuse patchset-created logic
    patchset_event = PatchSetCreatedEvent(
        type="patchset-created",
        change=change,
        patchSet=patchset,
        uploader=event.uploader,
        eventCreatedOn=event.eventCreatedOn
    )
    
    decision = handle_patchset_created(patchset_event)
    return decision

