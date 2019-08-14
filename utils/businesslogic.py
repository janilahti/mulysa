from datetime import date, timedelta

from users.models import BankTransaction, MemberService, ServiceSubscription


"""
Implements business logic for the membership services.

Not mature but seems to do the trick more or less right.
"""
class BusinessLogic:
    # Called when a new transaction has been added into database
    @staticmethod
    def new_transaction(transaction):
        print('New transaction', transaction)
        if transaction.user:
            transaction.user.log('Bank transaction of ' +
                            str(transaction.amount) + '€ dated ' + str(transaction.date))
            BusinessLogic.updateuser(transaction.user)
    @staticmethod
    def servicesubscription_state_changed(subscription, oldstate, newstate):
        subscription.user.log('Service ' + subscription.service.name + ' state changed from ' + oldstate + ' to ' + newstate)

    # Updates the user's status based on the data in database. Can be called from outside.
    @staticmethod
    def updateuser(user):
        servicesubscriptions = ServiceSubscription.objects.filter(user=user)

        print('Updating user data for', user)
        for subscription in servicesubscriptions:
            print('Examining', subscription)
            BusinessLogic.updatesubscription(user, subscription, servicesubscriptions)
            BusinessLogic.check_servicesubscription_state(subscription)

    # Updates a single subscription status for given user (used by updateuser)
    @staticmethod
    def updatesubscription(user, subscription, servicesubscriptions):
        print('Updating ', subscription, 'for', user)
        if subscription.state == ServiceSubscription.SUSPENDED:
            print('Service is suspended - no action')
            return

        services_that_pay_this = MemberService.objects.filter(pays_also_service=subscription.service)
        for service in services_that_pay_this:
            if BusinessLogic.user_is_subscribed_to(servicesubscriptions, service):
                print('Service is paid by ', service, ' which user is subscribed so skipping this service.')
                return

        transactions = BankTransaction.objects.filter(user=user,has_been_used=False).order_by('date')

        for transaction in transactions:
            if BusinessLogic.transaction_pays_service(transaction, subscription.service):
                print('Transaction is new and pays for service', subscription.service)
                BusinessLogic.service_paid_by_transaction(subscription, transaction)
            else:
                print('Transaction does not pay service', subscription.service)

    # Checks if given transaction pays the service
    @staticmethod
    def transaction_pays_service(transaction, service):
        if service.cost_min and transaction.amount < service.cost_min:
            return False
        if service.cost_max and transaction.amount > service.cost_max:
            return False
        if not service.cost_min and transaction.amount < service.cost:
            return False
        return True

    # Returns True if user (whose servicesubscriptions is given) is subscribed to given service
    @staticmethod
    def user_is_subscribed_to(servicesubscriptions, service):
        for subscription in servicesubscriptions:
            if subscription.service == service:
                return True
        return False

    # Called if transaction actually pays for extra time on given service subscription
    @staticmethod
    def service_paid_by_transaction(servicesubscription, transaction):
        # How many days to add to subscription's paid until
        days_to_add = timedelta(days=servicesubscription.service.days_per_payment)

        # First payment - initialize with payment date and add first time bonus days
        if not servicesubscription.paid_until:
            bonus_days = timedelta(days=servicesubscription.service.days_bonus_for_first)
            print(servicesubscription, 'paid for first time, adding bonus of', bonus_days)
            days_to_add = days_to_add + bonus_days
            servicesubscription.paid_until = transaction.date

        # Add days and mark this transaction to be the last payment
        servicesubscription.paid_until = (servicesubscription.paid_until + days_to_add)
        servicesubscription.last_payment = transaction
        servicesubscription.save()

        # Mark transaction as used
        transaction.has_been_used = True
        transaction.save()

        servicesubscription.user.log(str(servicesubscription) + ' is now paid until ' +
                                     str(servicesubscription.paid_until) + ' due to payment ' + str(transaction))

        # Todo: emit signals?

        # Handle case where this service also pays for another service
        if servicesubscription.service.pays_also_service:
            # All subscription for current user paid by this service
            paid_servicesubscriptions = ServiceSubscription.objects.filter(
                user=servicesubscription.user, service=servicesubscription.service.pays_also_service)
            for paid_servicesubscription in paid_servicesubscriptions:
                print(str(servicesubscription) + ' also pays for ' + str(paid_servicesubscription))
                if paid_servicesubscription.state == ServiceSubscription.SUSPENDED:
                    print('Service is suspended - no action')
                else:
                    extra_days = timedelta(days=paid_servicesubscription.service.days_per_payment)
                    paid_servicesubscription.paid_until = transaction.date + extra_days
                    paid_servicesubscription.last_payment = transaction
                    paid_servicesubscription.save()
                    servicesubscription.user.log(str(paid_servicesubscription) + ' is now paid until ' +
                                                 str(paid_servicesubscription.paid_until) + ' due to ' +
                                                 str(servicesubscription.service) + ' was paid')

                    BusinessLogic.check_servicesubscription_state(paid_servicesubscription)

    """
    Checks if the servicesubscription state needs to be changed due to paid_until changed.
    """
    @staticmethod
    def check_servicesubscription_state(subscription):
        # We do nothing if subscription is suspended
        if subscription.state == ServiceSubscription.SUSPENDED:
            return

        oldstate = subscription.state

        # Check if the service has been overdue and can be activated
        if subscription.state == ServiceSubscription.OVERDUE \
                and subscription.paid_until \
                and subscription.paid_until > date.today():
            subscription.state = ServiceSubscription.ACTIVE
            subscription.save()
            BusinessLogic.servicesubscription_state_changed(subscription, oldstate, subscription.state)

        # Check if the service becomes overdue
        if subscription.state == ServiceSubscription.ACTIVE \
                and subscription.paid_until \
                and subscription.paid_until < date.today():
            print(str(subscription) + ' payment overdue so changing state to OVERDUE')
            subscription.state = ServiceSubscription.OVERDUE
            subscription.save()
            BusinessLogic.servicesubscription_state_changed(subscription, oldstate, subscription.state)
