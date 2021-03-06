from rest_framework import permissions
from musette import utils


class ForumPermissions(permissions.BasePermission):
    """
    Check if is superuser for can crete, remove, etc.
    """
    def has_object_permission(self, request, view, obj):
        # Allow get requests for all
        if request.method == 'GET':
            return True
        else:
            # Get is moderator forum
            if hasattr(obj, 'forum'):
                forum = obj.forum
            elif hasattr(obj, 'topic'):
                forum = obj.topic.forum
            else:
                forum = None
            is_moderator = utils.is_user_moderator_forum(forum, request.user)

            # Only allow if is superuser or moderator or creted topic
            return (
                request.user.is_superuser or
                is_moderator or
                obj.user == request.user
            )


