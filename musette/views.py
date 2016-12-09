import base64
import json
import redis
from itertools import chain

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import (
    password_reset, password_reset_complete,
    password_reset_confirm
)
from django.core.mail import send_mail
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.template import defaultfilters
from django.views.generic import View
from django.views.generic.edit import FormView
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.utils.html import conditional_escape
from django.utils.text import Truncator
from django.utils.translation import ugettext_lazy as _

from musette import forms, models, utils


class LoginView(FormView):
    """
    Login View
    """
    template_name = "musette/login.html"
    form_class = forms.FormLogin
    success_url = "/forums/"

    def get(self, request, *args, **kwargs):
        # Check if is logged, if is trur redirect to home
        if request.user.is_authenticated():
            return ForumsView.as_view()(request)
        else:
            # No is logged, redirecto index login
            data = {
                'form': self.form_class
            }
            return render(request, self.template_name, data)

    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        # Check if is authenticated and form valid
        if not request.user.is_authenticated():
            if form.is_valid():
                # This method is one method of class
                # FormLogin in forms.py and is the
                # responsible of authenticate to user
                user = form.form_authenticate()
                if user:
                    if user.is_active:
                        # Login is correct
                        login(request, user)
                        return redirect("forums")
                    else:
                        messages.error(request, _("The user is not active"))
                        return self.form_invalid(form, **kwargs)
                else:
                    return self.form_invalid(form, **kwargs)
            else:
                return self.form_invalid(form, **kwargs)
        else:
            return redirect("forums")


class LogoutView(View):
    """
    View logout
    """
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            logout(request)

        return redirect("forums")


class SignUpView(FormView):
    """
    This view is responsible of
    create one new user
    """
    template_name = "musette/signup.html"
    form_class = forms.FormSignUp
    success_url = '/join/'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            return redirect("forums")
        else:
            data = {'form': self.form_class}
            return render(request, self.template_name, data)

    def post(self, request, *args, **kwargs):
        form_class = self.get_form_class()
        form = self.get_form(form_class)

        if not request.user.is_authenticated():
            if form.is_valid():
                form.create_user()
                msj = ""
                msj += "Registration was successful. Please, check your email "
                msj += "to validate the account."
                messages.success(request, _(msj))
                return self.form_valid(form, **kwargs)
            else:
                messages.error(request, _("Form invalid"))
                return self.form_invalid(form, **kwargs)
        else:
            return redirect("forums")


class ConfirmEmailView(View):
    """
    Form confirm email
    """
    template_name = "musette/confirm_email.html"

    def get(self, request, username, activation_key, *args, **kwargs):
        if request.user.is_authenticated():
            return redirect("forums")

        # Decoding username
        username = base64.b64decode(username.encode("utf-8")).decode("ascii")
        # Parameters for template
        data = {'username': username}

        # Get model profile
        ModelProfile = utils.get_main_model_profile()

        # Check if not expired key
        user_profile = get_object_or_404(
            ModelProfile, activation_key=activation_key
        )

        if user_profile.key_expires < timezone.now():
            return render(request, "musette/confirm_email_expired.html", data)

        # Active user
        user = get_object_or_404(User, username=username)
        user.is_active = True
        user.save()
        return render(request, self.template_name, data)


class NewKeyActivationView(View):
    """
    View for get a new key activation
    """
    template_name = "musette/confirm_email_expired.html"

    def post(self, request, username, *args, **kwargs):
        if request.user.is_authenticated():
            return redirect("forums")

        user = get_object_or_404(User, username=username)
        email = user.email

        # For confirm email
        data = utils.get_data_confirm_email(email)

        # Get model profile
        ModelProfile = utils.get_main_model_profile()

        # Update activation key
        profile = get_object_or_404(ModelProfile, iduser=user)
        profile.activation_key = data['activation_key']
        profile.key_expires = data['key_expires']
        profile.save()

        # Send email for confirm user
        utils.send_welcome_email(email, username, data['activation_key'])
        data = {'username': username, 'new_key': True}
        return render(request, self.template_name, data)


def reset_password(request):
    """
    This view contains the form
    for reset password of user
    """
    if request.user.is_authenticated():
        return redirect("forums")

    if request.method == "POST":
        messages.success(request, _('Please, check your email'))

    return password_reset(
        request,
        template_name='musette/password_reset_form.html',
        email_template_name='musette/password_reset_email.html',
        subject_template_name='musette/password_reset_subject.txt',
        password_reset_form=PasswordResetForm,
        token_generator=default_token_generator,
        post_reset_redirect='password_reset',
        from_email=None,
        extra_context=None,
        html_email_template_name=None
    )


def reset_pass_confirm(request, uidb64, token):
    """
    This view display form reset confirm pass
    """
    if request.user.is_authenticated():
        return redirect("forums")

    return password_reset_confirm(
        request, uidb64=uidb64, token=token,
        template_name='musette/password_reset_confirm.html',
        token_generator=default_token_generator,
        set_password_form=SetPasswordForm,
        post_reset_redirect=None,
        extra_context=None
    )


def reset_done_pass(request):
    """
    This view display messages
    that successful reset pass
    """
    if request.user.is_authenticated():
        return redirect("forums")

    return password_reset_complete(
        request, extra_context=None,
        template_name='musette/password_reset_complete.html',
    )


class ForumsView(View):
    """
    This view display all forum registered
    """
    template_name = "musette/index.html"

    def get(self, request, *args, **kwargs):
        # Get categories that not hidden
        categories = models.Category.objects.filter(hidden=False)

        data = {
            'categories': categories
        }

        return render(request, self.template_name, data)


class ForumView(View):
    """
    This view display one forum registered
    """
    def get(self, request, forum, *args, **kwargs):

        template_name = "musette/forum_index.html"
        page_template = "musette/forum.html"

        # Get topics forum
        forum = get_object_or_404(models.Forum, name=forum, hidden=False)
        topics = models.Topic.objects.filter(
            forum_id=forum.idforum
        ).order_by("-is_top", "-date")

        # Get forum childs
        forums_childs = models.Forum.objects.filter(parent=forum, hidden=False)

        iduser = request.user.id
        if iduser:
            try:
                models.Register.objects.get(
                    forum_id=forum.idforum, user_id=iduser
                )
                register = True
            except models.Register.DoesNotExist:
                register = False

        else:
            register = False

        data = {
            'forum': forum,
            'forums_childs': forums_childs,
            'topics': topics,
            'register': register
        }

        if request.is_ajax():
            template_name = page_template

        return render(request, template_name, data)


class TopicView(View):
    """
    This view display one Topic of forum
    """
    def get(self, request, forum, slug, idtopic, *args, **kwargs):

        template_name = "musette/topic_index.html"
        page_template = "musette/topic.html"

        # Get topic
        forum = get_object_or_404(models.Forum, name=forum, hidden=False)
        topic = get_object_or_404(models.Topic, idtopic=idtopic, slug=slug)

        # Form for comments
        form_comment = forms.FormAddComment()

        # Get comments of the topic
        comments = models.Comment.objects.filter(topic_id=idtopic)

        # Get photo of created user topic
        photo = utils.get_photo_profile(topic.user.id)

        data = {
            'topic': topic,
            'form_comment': form_comment,
            'comments': comments,
            'photo': photo
        }

        if request.is_ajax():
            template_name = page_template
        return render(request, template_name, data)


class NewTopicView(FormView):
    """
    This view allowed add new topic
    """
    template_name = "musette/new_topic.html"
    form_class = forms.FormAddTopic

    def get_success_url(self):
        return '/forum/' + self.kwargs['forum']

    def get(self, request, forum, *args, **kwargs):

        data = {
            'form': self.form_class,
            'forum': forum,
        }
        return render(request, self.template_name, data)

    def post(self, request, forum, *args, **kwargs):
        # Form new topic
        form = forms.FormAddTopic(request.POST, request.FILES)

        if form.is_valid():
            obj = form.save(commit=False)

            now = timezone.now()
            user = User.objects.get(id=request.user.id)
            forum = get_object_or_404(models.Forum, name=forum)
            title = conditional_escape(request.POST['title'])

            obj.date = now
            obj.user = user
            obj.forum = forum
            obj.title = title
            obj.slug = defaultfilters.slugify(request.POST['title'])

            # If has attachment
            if 'attachment' in request.FILES:
                id_attachment = get_random_string(length=32)
                obj.id_attachment = id_attachment

                file_name = request.FILES['attachment']
                obj.attachment = file_name

            # If the forum is moderate
            if forum.is_moderate:
                # If is moderator, so the topic is moderate
                if request.user in forum.moderators.all():
                    obj.moderate = True
                else:
                    obj.moderate = False

                    # Get moderators forum
                    for moderator in forum.moderators.all():
                        # Send email to moderator
                        if settings.SITE_URL.endswith("/"):
                            site = settings.SITE_URL + "forum/" + forum.name
                        else:
                            site = settings.SITE_URL + "/forum/" + forum.name

                        title_email = "New notification " + settings.SITE_NAME
                        message = "You have one new topic: " + site
                        email_from = settings.EMAIL_MUSETTE

                        email_moderator = moderator.email
                        if email_from:
                            send_mail(
                                title_email, message, email_from,
                                [email_moderator], fail_silently=False
                            )
            else:
                obj.moderate = True

            # Save topic
            obj.save()
            messages.success(
                request, _("The topic '%(topic)s' was successfully created")
                % {'topic': obj.title}
            )
            return self.form_valid(form, **kwargs)
        else:
            messages.error(request, _("Form invalid"))
            return self.form_invalid(form, **kwargs)


class EditTopicView(FormView):
    """
    This view allowed edit topic
    """
    template_name = "musette/edit_topic.html"
    form_class = forms.FormEditTopic

    def get_success_url(self):
        return '/forum/' + self.kwargs['forum']

    def get(self, request, forum, idtopic, *args, **kwargs):
        # Get topic
        topic = get_object_or_404(
            models.Topic, idtopic=idtopic, user_id=request.user.id
        )

        # Init fields form
        form = forms.FormEditTopic(instance=topic)

        data = {
            'form': form,
            'forum': forum,
            'topic': topic,
        }

        return render(request, self.template_name, data)

    def post(self, request, forum, idtopic, *args, **kwargs):
        # Get topic
        topic = get_object_or_404(
            models.Topic, idtopic=idtopic, user_id=request.user.id
        )
        file_name = topic.attachment

        # Get form
        form = forms.FormEditTopic(request.POST, request.FILES, instance=topic)
        file_path = settings.MEDIA_ROOT

        if form.is_valid():

            obj = form.save(commit=False)

            title = conditional_escape(request.POST['title'])
            slug = defaultfilters.slugify(request.POST['title'])

            obj.title = title
            obj.slug = slug

            # If check field clear, remove file when update
            if 'attachment-clear' in request.POST:
                route_file = utils.get_route_file(file_path, file_name.name)

                try:
                    remove_file(route_file)
                except Exception:
                    pass

            # If has attachment
            if 'attachment' in request.FILES:

                if not topic.id_attachment:
                    id_attachment = get_random_string(length=32)
                    obj.id_attachment = id_attachment

                file_name_post = request.FILES['attachment']
                obj.attachment = file_name_post

                # Route previous file
                route_file = utils.get_route_file(file_path, file_name.name)

                try:
                    # If a previous file exists it removed
                    remove_file(route_file)
                except Exception:
                    pass

            # Update topic
            form.save()

            messages.success(
                request,
                _("The topic '%(topic)s' was successfully edited")
                % {'topic': obj.title}
            )
            return self.form_valid(form, **kwargs)
        else:
            messages.error(request, _("Form invalid"))
            return self.form_invalid(form, **kwargs)


class DeleteTopicView(View):
    """
    This view will delete one topic
    """
    def get(self, request, forum, idtopic, *args, **kwargs):
        # Previouly verify that exists the topic
        topic = get_object_or_404(
            models.Topic, idtopic=idtopic, user_id=request.user.id
        )

        # Get data topic
        iduser_topic = topic.user_id
        title_topic = topic.title

        # If my user so delete
        if request.user.id == iduser_topic:
            utils.remove_folder_attachment(idtopic)
            models.Topic.objects.filter(
                idtopic=idtopic, user_id=iduser_topic
            ).delete()
            messages.success(
                request, _("The topic '%(topic)s' was successfully deleted")
                % {'topic': title_topic}
            )
        else:
            raise Http404

        return redirect('forum', forum)


class NewCommentView(View):
    """
    This view allowed add new comment to topic
    """
    def get(self, request, forum, slug, idtopic, *args, **kwargs):
        raise Http404()

    def post(self, request, forum, slug, idtopic, *args, **kwargs):
        # Form new comment
        form = forms.FormAddComment(request.POST)

        param = ""
        param = forum + "/" + slug
        param = param + "/" + str(idtopic) + "/"
        url = '/topic/' + param

        if form.is_valid():
            obj = form.save(commit=False)

            # Save new comment
            now = timezone.now()
            user = User.objects.get(id=request.user.id)
            topic = get_object_or_404(models.Topic, idtopic=idtopic)

            obj.date = now
            obj.user = user
            obj.topic_id = topic.idtopic

            obj.save()

            # Redis instance
            r = redis.StrictRedis()

            idcomment = obj.idcomment

            # Data for notification real time
            comment = models.Comment.objects.get(idcomment=idcomment)
            username = request.user.username

            # Get photo profile
            photo = utils.get_photo_profile(request.user.id)

            # Data for notification real time
            description = Truncator(comment.description).chars(100)

            # Send notifications
            lista_us = utils.get_users_topic(topic, request.user.id)
            lista_email = []

            # If not exists user that create topic, add
            user_original_topic = topic.user.id
            user_email = topic.user.email

            if not (user_original_topic in lista_us):
                lista_us.append(user_original_topic)
                lista_email.append(user_email)
            else:
                user_original_topic = None

            for user in lista_us:
                if user_original_topic != request.user.id:
                    notification = models.Notification(
                        iduser=user, is_view=False,
                        idobject=idcomment, date=now,
                        is_topic=False, is_comment=True
                    )
                    notification.save()

            # Send email notification
            if settings.SITE_URL.endswith("/"):
                site = settings.SITE_URL[:-1]
            else:
                site = settings.SITE_URL

            title_email = "New notification " + settings.SITE_NAME
            message = "You have one new comment in the topic: " + site + url
            email_from = settings.EMAIL_MUSETTE
            if email_from:
                send_mail(
                    title_email, message, email_from,
                    lista_email, fail_silently=False
                )

            # Data necessary for realtime
            data = {
                "description": description,
                "topic": comment.topic.title,
                "idtopic": comment.topic.idtopic,
                "slug": comment.topic.slug,
                "settings_static": settings.STATIC_URL,
                "username": username,
                "forum": forum,
                "lista_us": lista_us,
                "photo": photo
            }

            # Add to real time new notification
            json_data = json.dumps(data)
            r.publish('notifications', json_data)

            messages.success(request, _("Added new comment"))
            return HttpResponseRedirect(url)
        else:
            messages.error(request, _("Field required"))
            return HttpResponseRedirect(url)


class EditCommentView(View):
    """
    This view allowed edit comment to topic
    """
    def get(self, request, forum, slug, idtopic, idcomment, *args, **kwargs):
        raise Http404()

    def post(self, request, forum, slug, idtopic, idcomment, *args, **kwargs):
        param = ""
        param = forum + "/" + slug
        param = param + "/" + str(idtopic) + "/"
        url = '/topic/' + param

        # Valid if has description
        description = request.POST.get('update_description')
        if description:
            # Edit comment
            iduser = request.user.id
            models.Comment.objects.filter(
                idcomment=idcomment, user=iduser
            ).update(
                description=description
            )

            messages.success(request, _("Comment edited"))
            return HttpResponseRedirect(url)
        else:
            return HttpResponseRedirect(url)


class DeleteCommentView(View):
    """
    This view allowed remove comment to topic
    """
    def get(self, request, forum, slug, idtopic, idcomment, *args, **kwargs):
        raise Http404()

    def post(self, request, forum, slug, idtopic, idcomment, *args, **kwargs):
        param = ""
        param = forum + "/" + slug
        param = param + "/" + str(idtopic) + "/"
        url = '/topic/' + param

        # Delete comment and notification
        try:
            iduser = request.user.id
            models.Comment.objects.filter(
                idcomment=idcomment, user=iduser
            ).delete()
            models.Notification.objects.filter(idobject=idcomment).delete()

            messages.success(request, _("Comment deleted"))
            return HttpResponseRedirect(url)
        except Exception:
            return HttpResponseRedirect(url)


class AllNotification(View):
    """
    This view return all notification and paginate
    """
    def get(self, request, *args, **kwargs):
        template_name = "musette/all_notification_index.html"
        page_template = "musette/all_notification.html"

        iduser = request.user.id

        # Set all notification like view
        models.Notification.objects.filter(iduser=iduser).update(is_view=True)

        # Get all notification user
        notifications = utils.get_notifications(iduser)
        data = {
            'notifications': notifications,
        }

        if request.is_ajax():
            template_name = page_template
        return render(request, template_name, data)


def SetNotifications(request):
    """
    This view set all views notifications in true
    """
    iduser = request.user.id
    models.Notification.objects.filter(iduser=iduser).update(is_view=True)

    return HttpResponse("Ok")


class AddRegisterView(View):
    """
    This view add register to forum
    """
    def get(self, request, forum, *args, **kwargs):
        raise Http404()

    def post(self, request, forum, *args, **kwargs):
        url = '/forum/' + forum + "/"

        # Get data
        forum = get_object_or_404(models.Forum, name=forum, hidden=False)
        idforum = forum.idforum
        iduser = request.user.id
        date = timezone.now()

        # Add new register
        register = models.Register(
            forum_id=idforum, user_id=iduser,
            date=date
        )
        register.save()
        messages.success(request, _("You have successfully registered"))
        return HttpResponseRedirect(url)


class UnregisterView(View):
    """
    This view remove register to forum
    """
    def get(self, request, forum, *args, **kwargs):
        raise Http404()

    def post(self, request, forum, *args, **kwargs):
        url = '/forum/' + forum + "/"

        # Get data
        forum = get_object_or_404(models.Forum, name=forum, hidden=False)
        idforum = forum.idforum
        iduser = request.user.id

        # Remove register
        models.Register.objects.filter(
            forum_id=idforum, user_id=iduser,
        ).delete()

        messages.success(request, _("Registration was successfully canceled"))
        return HttpResponseRedirect(url)


class UsersForumView(View):
    """
    This view display users register in forum
    """
    def get(self, request, forum, *args, **kwargs):

        template_name = "musette/users_forum_index.html"
        page_template = "musette/users_forum.html"

        # Get register users
        forum = get_object_or_404(models.Forum, name=forum, hidden=False)
        registers = forum.register_forums.all()

        # Add moderator to users
        users = list(chain(registers, forum.moderators.all()))

        data = {
            'forum': forum,
            'users': users,
        }

        if request.is_ajax():
            template_name = page_template
        return render(request, template_name, data)

    def post(self, request, forum, *args, **kwargs):
        raise Http404()


class TopicSearch(View):
    """
    This view django, display results of search of topics
    """
    def get(self, request, forum, *args, **kwargs):
        template_name = "musette/topic_search_index.html"
        page_template = "musette/topic_search.html"

        # Get param to search
        search = request.GET.get('q')

        # Get id forum
        forum = get_object_or_404(models.Forum, name=forum)
        idforum = forum.idforum

        # Search topics
        topics = models.Topic.objects.filter(
            forum_id=idforum, title__icontains=search
        )

        data = {
            'topics': topics,
            'forum': forum,
        }

        if request.is_ajax():
            template_name = page_template
        return render(request, template_name, data)


class ProfileView(View):
    """
    This view django, display results of the profile
    """
    def get(self, request, username, *args, **kwargs):
        template_name = "musette/profile.html"

        # Get user param
        user = get_object_or_404(User, username=username)
        iduser = user.id

        # Get model extend Profile
        ModelProfile = utils.get_main_model_profile()

        # Get name app of the extend model Profile
        app = utils.get_app_model(ModelProfile)

        # Check if the model profile is extended
        count_fields_model = utils.get_count_fields_model(ModelProfile)
        count_fields_abstract = utils.get_count_fields_model(
            models.AbstractProfile
        )
        if count_fields_model > count_fields_abstract:
            model_profile_is_extend = True
        else:
            model_profile_is_extend = False
        profile = get_object_or_404(ModelProfile, iduser=iduser)

        photo = utils.get_photo_profile(iduser)

        data = {
            'profile': profile,
            'photo': photo,
            'user': request.user,
            'app': app,
            'model_profile_is_extend': model_profile_is_extend
        }

        return render(request, template_name, data)


class EditProfileView(FormView):
    """
    This view allowed edit profile
    """
    template_name = "musette/edit_profile.html"
    form_class = forms.FormEditProfile

    def get_success_url(self):
        return '/profile/' + self.kwargs['username']

    def get(self, request, username, *args, **kwargs):

        ModelProfile = utils.get_main_model_profile()
        profile = get_object_or_404(
            ModelProfile, iduser=request.user.id
        )

        # Init fields form
        form = forms.FormEditProfile(instance=profile)

        data = {
            'form': form
        }

        return render(request, self.template_name, data)

    def post(self, request, username, *args, **kwargs):

        ModelProfile = utils.get_main_model_profile()
        profile = get_object_or_404(
            ModelProfile, iduser=request.user.id
        )

        file_name = profile.photo

        form = forms.FormEditProfile(
            request.POST, request.FILES, instance=profile
        )
        file_path = settings.MEDIA_ROOT

        if form.is_valid():

            obj = form.save(commit=False)
            about = request.POST['about']
            obj.about = about

            # If check field clear, remove file when update
            if 'attachment-clear' in request.POST:
                route_file = utils.get_route_file(file_path, file_name.name)

                try:
                    utils.remove_file(route_file)
                except Exception:
                    pass

            if 'attachment' in request.FILES:

                if not obj.id_attachment:
                    id_attachment = get_random_string(length=32)
                    obj.id_attachment = id_attachment

                file_name_post = request.FILES['photo']
                obj.photo = file_name_post

                # Route previous file
                route_file = utils.get_route_file(file_path, file_name.name)

                try:
                    # If a previous file exists it removed
                    utils.remove_file(route_file)
                except Exception:
                    pass

            # Update profile
            form.save()

            messages.success(
                request,
                _("Your profile was successfully edited")
            )
            return self.form_valid(form, **kwargs)
        else:
            messages.error(request, _("Form invalid"))
            return self.form_invalid(form, **kwargs)
